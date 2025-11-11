#
# utils module - common functions for reportbug UIs
#   Written by Chris Lawrence <lawrencc@debian.org>
#   Copyright (C) 1999-2008 Chris Lawrence
#   Copyright (C) 2008-2021 Sandro Tosi <morph@debian.org>
#
# This program is freely distributable per the following license:
#
#  Permission to use, copy, modify, and distribute this software and its
#  documentation for any purpose and without fee is hereby granted,
#  provided that the above copyright notice appears in all copies and that
#  both that copyright notice and this permission notice appear in
#  supporting documentation.
#
#  I DISCLAIM ALL WARRANTIES WITH REGARD TO THIS SOFTWARE, INCLUDING ALL
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS, IN NO EVENT SHALL I
#  BE LIABLE FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY
#  DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
#  WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
#  ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS
#  SOFTWARE.

import sys
import os
import re
import platform

try:
    import pwd
    from .tempfiles import TempFile, cleanup_temp_file
except ImportError as e:
    if platform.system() == 'Windows':
        pass
    else:
        print(e)
        sys.exit(1)
import shlex
import email
import email.policy
import socket
import subprocess
import apt
import gzip
import urllib

from .urlutils import open_url
from .mailer import MUA

# Paths for dpkg
DPKGLIB = '/var/lib/dpkg'
AVAILDB = os.path.join(DPKGLIB, 'available')
STATUSDB = os.path.join(DPKGLIB, 'status')

# Headers other than these become email headers for debbugs servers
PSEUDOHEADERS = ('Package', 'Source', 'Version', 'Severity', 'File', 'Tags',
                 'Justification', 'Followup-For', 'Owner', 'User', 'Usertags',
                 'Forwarded', 'Control', 'X-Debbugs-Cc')
# These pseudo-headers can be repeated in the report
REPEATABLE_PSEUDOHEADERS = ['Control',]

MODES = {'novice': 'Offer simple prompts, bypassing technical questions.',
         'standard': 'Offer more extensive prompts, including asking about '
                     'things that a moderately sophisticated user would be expected to '
                     'know about Debian.',
         'advanced': 'Like standard, but assumes you know a bit more about '
                     'Debian, including "incoming".',
         'expert': 'Bypass most handholding measures and preliminary triage '
                   'routines.  This mode should not be used by people unfamiliar with '
                   'Debian\'s policies and operating procedures.'}
MODELIST = ['novice', 'standard', 'advanced', 'expert']
for mode in MODELIST:
    exec('MODE_%s=%d' % (mode.upper(), MODELIST.index(mode)))
del mode

# moved here since it needs the MODE_* vars to be defined
from . import debbugs
# it needs to be imported after debbugs
#from .ui import text_ui as ui

from reportbug.ui import AVAILABLE_UIS

NEWBIELINE = """Dear Maintainer,

*** Reporter, please consider answering these questions, where appropriate ***

   * What led up to the situation?
   * What exactly did you do (or not do) that was effective (or
     ineffective)?
   * What was the outcome of this action?
   * What outcome did you expect instead?

*** End of the template - remove these template lines ***"""

fhs_directories = ['/', '/usr', '/usr/share', '/var', '/usr/X11R6',
                   '/usr/man', '/usr/doc', '/usr/bin']

# A map between codenames and suites
CODENAME2SUITE = {'wheezy': 'oldoldoldoldoldstable',
                  'jessie': 'oldoldoldoldstable',
                  'stretch': 'oldoldoldstable',
                  'buster': 'oldoldstable',
                  'bullseye': 'oldstable',
                  'bookworm': 'stable',
                  'trixie': 'testing',
                  'forky': 'next-testing',
                  'sid': 'unstable',
                  'experimental': 'experimental'}
SUITE2CODENAME = dict([(suite, codename) for codename, suite in list(CODENAME2SUITE.items())])

_apt_cache = apt.Cache()

def realpath(filename):
    filename = os.path.abspath(filename)

    bits = filename.split('/')
    for i in range(2, len(bits) + 1):
        component = '/'.join(bits[0:i])
        if component in fhs_directories:
            continue

        if os.path.islink(component):
            resolved = os.readlink(component)
            (dir, file) = os.path.split(component)
            resolved = os.path.normpath(os.path.join(dir, resolved))
            newpath = os.path.join(*[resolved] + bits[i:])
            return realpath(newpath)

    return filename


pathdirs = ['/usr/sbin', '/usr/bin', '/sbin', '/bin', '/usr/X11R6/bin',
            '/usr/games']


def search_path_for(filename):
    d, f = os.path.split(filename)
    if d:
        return realpath(filename)

    path = os.environ.get("PATH", os.defpath).split(':')
    for d in pathdirs:
        if d not in path:
            path.append(d)

    for d in path:
        fullname = os.path.join(d, f)
        if os.path.exists(fullname):
            return realpath(fullname)
    return None


def which_editor(specified_editor=None):
    """ Determine which editor program to use.

        :parameters:
          `specified_editor`
            Specified editor for reportbug, to be used in preference
            to other settings.

        :return value:
            Command to invoke for selected editor program.

        """
    debian_default_editor = "/usr/bin/sensible-editor"
    for editor in [specified_editor,
                   os.environ.get("VISUAL"),
                   os.environ.get("EDITOR"),
                   debian_default_editor]:
        if editor:
            break

    return editor


def glob_escape(filename):
    filename = re.sub(r'([*?\[\]])', r'\\\1', filename)
    return filename


def search_pipe(searchfile, use_dlocate=True):
    arg = shlex.quote(searchfile)
    if use_dlocate and os.path.exists('/usr/bin/dlocate'):
        pipe = os.popen('COLUMNS=79 dlocate -S %s 2>/dev/null' % arg)
    else:
        use_dlocate = False
        pipe = os.popen('COLUMNS=79 dpkg --search %s 2>/dev/null' % arg)
    return (pipe, use_dlocate)


def get_command_output(cmd):
    use_shell = False
    if isinstance(cmd, str) and ' ' in cmd:
        use_shell = True
    return subprocess.run(cmd, shell=use_shell, stdout=subprocess.PIPE).stdout.decode(errors='backslashreplace')


def query_dpkg_for(filename, use_dlocate=True):
    try:
        x = os.getcwd()
    except OSError:
        os.chdir('/')
    searchfilename = glob_escape(filename)
    (pipe, dlocate_used) = search_pipe(searchfilename, use_dlocate)
    packages = {}

    for line in pipe:
        line = line.strip()
        # Ignore diversions
        if 'diversion by' in line:
            continue

        (package, path) = line.split(': ', 1)
        path = path.strip()
        packlist = package.split(', ')
        for package in packlist:
            if package in packages:
                packages[package].append(path)
            else:
                packages[package] = [path]
    pipe.close()
    # Try again without dlocate if no packages found
    if not packages and dlocate_used:
        _, packages = query_dpkg_for(filename, use_dlocate=False)

    # still not found?
    # dpkg and merged /usr do not work well together
    if not packages and filename.startswith(('/usr/bin', '/usr/lib', '/usr/sbin')):
        # try without '/usr'
        filename = filename[4:]
        return query_dpkg_for(filename)

    return filename, packages


def find_package_for(filename, pathonly=False):
    """Find the package(s) containing this file."""

    packages = {}

    # tries to match also files in /var/lib/dpkg/info/
    if filename.startswith('/var/lib/dpkg/info/'):
        dpkg_info = re.compile(r'/var/lib/dpkg/info/(.+)\.[^.]+')
        m = dpkg_info.match(filename)
        # callee want a dict as second pair element...
        packages[m.group(1)] = ''
        return (filename, packages)

    if filename[0] == '/':
        fn, pkglist = query_dpkg_for(filename)
        if pkglist:
            return fn, pkglist

    newfilename = search_path_for(filename)
    if pathonly and not newfilename:
        return (filename, None)
    return query_dpkg_for(newfilename or filename)


def find_rewritten(username):
    filename = '/etc/email-addresses'
    try:
        fp = open(filename, errors='backslashreplace')
    except (FileNotFoundError, IOError):
        return None
    try:
        for line in fp:
            line = line.strip().split('#')[0]
            if not line:
                continue
            try:
                name, alias = line.split(':')
                if name.strip() == username:
                    return alias.strip()
            except ValueError:
                print('Invalid entry in %s' % filename)
                return None
    finally:
        fp.close()


def check_email_addr(addr):
    """Simple check for email validity"""
    if '@' not in addr:
        return False
    if addr.count('@') != 1:
        return False
    localpart, domainpart = addr.split('@')
    if localpart.startswith('.') or localpart.endswith('.'):
        return False
    if '.' not in domainpart:
        return False
    if domainpart.startswith('.') or domainpart.endswith('.'):
        return False
    # known invalid addresses according to rfc2606
    if domainpart in ('localhost', 'example.com', 'example.net', 'example.org'):
        return False
    if domainpart.endswith(('.example', '.invalid', '.localhost', '.test',
            '.example.com', '.example.net', '.example.org')):
        return False

    return True


def get_email_addr(addr):
    return email.utils.getaddresses([addr,])[0]


def get_email(emailaddr='', realname=''):
    return get_email_addr(get_user_id(emailaddr, realname))


def get_user_id(emailaddr='', realname='', charset='utf-8'):
    uid = os.getuid()
    info = pwd.getpwuid(uid)
    emailaddr = (os.environ.get('REPORTBUGEMAIL', emailaddr) or
                 os.environ.get('DEBEMAIL') or os.environ.get('EMAIL'))

    emailaddr = emailaddr or find_rewritten(info[0]) or info[0]

    if '@' not in emailaddr:
        try:
            with open('/etc/mailname', 'r') as mf:
                domainname = mf.readline().strip()
        except (FileNotFoundError, IOError):
            domainname = socket.getfqdn()

        emailaddr = emailaddr + '@' + domainname

    # Handle EMAIL if it's formatted as 'Bob <bob@host>'.
    if '<' in emailaddr or '(' in emailaddr:
        realname, emailaddr = get_email_addr(emailaddr)

    if not realname:
        realname = (os.environ.get('DEBFULLNAME') or os.environ.get('DEBNAME')
                    or os.environ.get('NAME'))
        if not realname:
            realname = info[4].split(',', 1)[0]
            # Convert & in gecos field 4 to capitalized logname: #224231
            realname = realname.replace('&', info[0].capitalize())

    if not realname:
        return emailaddr

    return email.utils.formataddr((realname, emailaddr))


statuscache = {}


def get_package_status(package, avail=False):
    if not avail and package in statuscache:
        return statuscache[package]

    versionre = re.compile('Version: ')
    packagere = re.compile('Package: ')
    priorityre = re.compile('Priority: ')
    dependsre = re.compile('(Pre-)?Depends: ')
    recsre = re.compile('Recommends: ')
    suggestsre = re.compile('Suggests: ')
    conffilesre = re.compile('Conffiles:')
    maintre = re.compile('Maintainer: ')
    statusre = re.compile('Status: ')
    originre = re.compile('Origin: ')
    bugsre = re.compile('Bugs: ')
    descre = re.compile('Description(?:-[a-zA-Z]+)?: ')
    fullre = re.compile(' ')
    srcre = re.compile('Source: ')
    sectionre = re.compile('Section: ')

    pkgversion = pkgavail = maintainer = status = origin = None
    bugs = vendor = priority = desc = src_name = section = None
    conffiles = []
    fulldesc = []
    depends = []
    recommends = []
    suggests = []
    confmode = False
    descmode = False
    state = ''

    try:
        x = os.getcwd()
    except OSError:
        os.chdir('/')

    packarg = shlex.quote(package)
    if avail:
        output = get_command_output(
            "LC_ALL=C.UTF-8 apt-cache show %s 2>/dev/null" % packarg)
    else:
        # filter through dpkg-query to automatically append arch
        # qualifier in the cases where this is needed
        try:
            packarg = get_command_output(
                "dpkg-query -W -f='${binary:Package}\n' %s 2>/dev/null" % packarg).split()[0]
        except IndexError:
            pass
        output = get_command_output(
            "COLUMNS=79 dpkg --status %s 2>/dev/null" % packarg)

    for line in output.split(os.linesep):
        line = line.rstrip()
        if not line:
            continue

        if descmode:
            if line[0] == ' ':
                fulldesc.append(line)
            else:
                descmode = False

        if confmode:
            if line[:2] != ' /':
                confmode = False
            else:
                # re is used to identify also conffiles with spaces in the name
                conffiles += re.findall(r' (.+) ([0-9a-f]+).*$', line)

        if versionre.match(line):
            (crud, pkgversion) = line.split(": ", 1)
        elif statusre.match(line):
            (crud, status) = line.split(": ", 1)
        elif priorityre.match(line):
            (crud, priority) = line.split(": ", 1)
        elif packagere.match(line):
            (crud, pkgavail) = line.split(": ", 1)
        elif originre.match(line):
            (crud, origin) = line.split(": ", 1)
        elif bugsre.match(line):
            (crud, bugs) = line.split(": ", 1)
        elif descre.match(line) and not fulldesc:
            (crud, desc) = line.split(": ", 1)
            descmode = True
        elif dependsre.match(line):
            (crud, thisdepends) = line.split(": ", 1)
            # Remove versioning crud
            thisdepends = [[y.split()[0] for y in x.split('|')]
                           for x in (thisdepends.split(', '))]
            depends.extend(thisdepends)
        elif recsre.match(line):
            (crud, thisdepends) = line.split(": ", 1)
            # Remove versioning crud
            thisdepends = [[y.split()[0] for y in x.split('|')]
                           for x in (thisdepends.split(', '))]
            recommends.extend(thisdepends)
        elif suggestsre.match(line):
            (crud, thisdepends) = line.split(": ", 1)
            # Remove versioning crud
            thisdepends = [[y.split()[0] for y in x.split('|')]
                           for x in (thisdepends.split(', '))]
            suggests.extend(thisdepends)
        elif conffilesre.match(line):
            confmode = True
        elif maintre.match(line):
            crud, maintainer = line.split(": ", 1)
        elif srcre.match(line):
            crud, src_name = line.split(": ", 1)
            src_name = src_name.split()[0]
        elif sectionre.match(line):
            crud, section = line.split(": ", 1)

    installed = False
    if status:
        state = status.split()[2]
        installed = (state not in ('config-files', 'not-installed'))

    reportinfo = None
    if bugs:
        reportinfo = debbugs.parse_bts_url(bugs)
    elif origin:
        if origin in debbugs.SYSTEMS:
            vendor = debbugs.SYSTEMS[origin]['name']
            reportinfo = (debbugs.SYSTEMS[origin].get('type', 'debbugs'),
                          debbugs.SYSTEMS[origin]['btsroot'])
        else:
            vendor = origin.capitalize()
    else:
        vendor = ''

    info = (pkgversion, pkgavail, tuple(depends), tuple(recommends),
            tuple(conffiles),
            maintainer, installed, origin, vendor, reportinfo, priority,
            desc, src_name, os.linesep.join(fulldesc), state, tuple(suggests),
            section)

    if not avail:
        statuscache[package] = info
    return info


# dbase = []
# avail = []

# Object that essentially chunkifies the output of apt-cache dumpavail
class AvailDB(object):
    def __init__(self, fp=None, popenob=None):
        self.popenob = popenob
        if fp:
            self.fp = fp
        elif popenob:
            self.fp = popenob.stdout

    def __iter__(self):
        return self

    def __next__(self):
        chunk = ''
        while True:
            if self.popenob:
                if self.popenob.returncode:
                    break

            line = self.fp.readline()
            if not line:
                break

            if line == '\n':
                return chunk
            chunk += str(line)

        if chunk:
            return chunk

        raise StopIteration

    def __del__(self):
        # print >> sys.stderr, 'availdb cleanup', repr(self.popenob), repr(self.fp)
        if self.popenob:
            # Clear the pipe before shutting it down
            while True:
                if self.popenob.returncode:
                    break
                stuff = self.fp.read(65536)
                if not stuff:
                    break
            self.popenob.wait()
        if self.fp:
            self.fp.close()


def get_dpkg_database():
    try:
        fp = open(STATUSDB, errors="backslashreplace")
        if fp:
            return AvailDB(fp=fp)
    except IOError:
        print('Unable to open', STATUSDB, file=sys.stderr)
        sys.exit(1)


def get_avail_database():
    # print >> sys.stderr, 'Searching available database'
    subp = subprocess.Popen(('apt-cache', 'dumpavail'), stdout=subprocess.PIPE)
    return AvailDB(popenob=subp)


def get_source_name(package):
    try:
        return _apt_cache[package].versions[0].source_name
    except KeyError:
        pass
    # check if there is a source package with that name
    try:
        srcrecords = apt.apt_pkg.SourceRecords()
        if srcrecords.lookup(package):
            return srcrecords.package
    except apt.apt_pkg.Error as e:
        print(f"Cannot look up source package: '{e}'")
    return None


def get_source_package(package):
    packages = []
    retlist = []
    found = {}

    data = get_command_output('apt-cache showsrc ' + shlex.quote(package))
    binre = re.compile(r'^Binary: (.*)$')
    for line in data.split('\n'):
        m = binre.match(line)
        if m:
            packs = m.group(1)
            packlist = re.split(r',\s*', packs)
            packages += packlist

    for p in packages:
        try:
            desc = _apt_cache[p].versions[0].summary
        except KeyError:
            continue
        if desc and (p not in found):
            retlist += [(p, desc)]
            found[p] = desc

    retlist.sort()
    return retlist


def get_package_info(packages, skip_notfound=False):
    if not packages:
        return []

    packinfo = get_dpkg_database()
    pkgname = r'(?:[\S]+(?:\s+\(=[^()]+\))?(?:$|,\s+))'

    groupfor = {}
    searchpkgs = []
    searchbits = []
    for (group, package) in packages:
        groupfor[package] = group
        escpkg = re.escape(package)
        searchpkgs.append(escpkg + r'(?:\s+\(=[^()]+\))?')

    searchbits = [
        # Package regular expression
        r'^(?P<hdr>Package):\s+(' + '|'.join(searchpkgs) + ')$',
        # Provides regular expression
        r'^(?P<hdr>Provides):\s+' + pkgname + r'*(?P<pkg>' + '|'.join(searchpkgs) +
        r')(?:$|,\s+)' + pkgname + '*$'
    ]

    groups = list(groupfor.values())
    found = {}

    searchobs = [re.compile(x, re.MULTILINE) for x in searchbits]
    packob = re.compile('^Package: (?P<pkg>.*)$', re.MULTILINE)
    statob = re.compile('^Status: (?P<stat>.*)$', re.MULTILINE)
    versob = re.compile('^Version: (?P<vers>.*)$', re.MULTILINE)
    descob = re.compile('^Description(?:-[a-zA-Z]+)?: (?P<desc>.*)$', re.MULTILINE)

    ret = []
    for p in packinfo:
        for ob in searchobs:
            m = ob.search(p)
            if m:
                pack = packob.search(p).group('pkg')
                stat = statob.search(p).group('stat')
                sinfo = stat.split()
                stat = sinfo[0][0] + sinfo[2][0]
                # check if the package is installed, and in that case, retrieve
                # its information; if the first char is not 'i' or 'h' (install
                # or hold) or the second is 'n' (not-installed), then skip data
                # retrieval
                if stat[0] not in 'ih' or stat[1] == 'n':
                    continue

                if m.group('hdr') == 'Provides':
                    provides = m.group('pkg').split()[0]
                else:
                    provides = None

                vers = versob.search(p).group('vers')
                desc = descob.search(p).group('desc')

                info = (pack, stat, vers, desc, provides)
                ret.append(info)
                group = groupfor.get(pack)
                if group:
                    for item in group:
                        found[item] = True
                if provides not in found:
                    found[provides] = True

    if skip_notfound:
        return ret

    for group in groups:
        notfound = [x for x in group if x not in found]
        if len(notfound) == len(group):
            if group not in found:
                ret.append((' | '.join(group), 'pn', '<none>',
                            '(no description available)', None))

    return ret


def packages_providing(package):
    aret = get_package_info([((package,), package)], skip_notfound=True)
    ret = []
    for pkg in aret:
        ret.append((pkg[0], pkg[3]))

    return ret


def get_dependency_info(package, depends, rel="depends on"):
    if not depends:
        return ('\n%s %s no packages.\n' % (package, rel))

    dependencies = []
    for dep in depends:
        # drop possible architecture qualifier from package names
        dep = [d.split(':')[0] for d in dep]
        for bit in dep:
            dependencies.append((tuple(dep), bit))

    depinfo = "\nVersions of packages %s %s:\n" % (package, rel)

    packs = {}
    for info in get_package_info(dependencies):
        pkg = info[0]
        if pkg not in packs:
            packs[pkg] = info
        elif info[4]:
            if not packs[pkg][4]:
                packs[pkg] = info

    deplist = list(packs.values())
    deplist.sort()

    deplist2 = []
    # extract the info we need, also add provides where it fits
    for (pack, status, vers, desc, provides) in deplist:
        if provides:
            pack += ' [' + provides + ']'
        deplist2.append((pack, vers, status))
    deplist = deplist2

    # now we can compute the max possible value for each column, that can be the
    # max of all its values, or the space left from the other column; this way,
    # the sum of the 2 fields is never > 73 (hence the resulting line is <80
    # columns)
    maxp = max([len(x[0]) for x in deplist])
    maxv = max([len(x[1]) for x in deplist])
    widthp = min(maxp, 73 - maxv)
    widthv = min(maxv, 73 - widthp)

    for (pack, vers, status) in deplist:
        # we format the string specifying to align it in a field of a given
        # dimension (the first {width*}) but also limit its size (the second
        # {width*}
        info = '{0:3.3} {1:{widthp}.{widthp}}  {2:{widthv}.{widthv}}'.format(
            status, pack, vers, widthp=widthp, widthv=widthv)
        # remove tailing white spaces
        depinfo += info.rstrip() + '\n'

    return depinfo


def get_changed_config_files(conffiles, nocompress=False):
    confinfo = {}
    changed = []
    for (filename, md5sum) in conffiles:
        try:
            fp = open(filename, errors='backslashreplace')
        except IOError as msg:
            confinfo[filename] = msg
            continue

        filemd5 = get_command_output('md5sum ' + shlex.quote(filename)).split()[0]
        if filemd5 == md5sum:
            continue

        changed.append(filename)
        thisinfo = 'changed:\n'
        for line in fp:
            if not line:
                continue

            if line == '\n' and not nocompress:
                continue
            if line[0] == '#' and not nocompress:
                continue

            thisinfo += line

        confinfo[filename] = thisinfo

    return confinfo, changed


DISTORDER = ['oldstable', 'stable', 'testing', 'unstable', 'experimental']


def get_debian_release_info():
    debvers = debinfo = verfile = warn = ''
    dists = []
    output = get_command_output('apt-cache policy 2>/dev/null')
    if output:
        mre = re.compile(r'\s+(\d+)\s+.*$\s+release\s.*o=(Ubuntu|Debian|Debian Ports),a=([^,]+),', re.MULTILINE)
        found = {}
        # XXX: When Python 2.4 rolls around, rewrite this
        for match in mre.finditer(output):
            pword, distname = match.group(1, 3)
            if distname in DISTORDER:
                pri, dist = int(pword), DISTORDER.index(distname)
            else:
                pri, dist = int(pword), len(DISTORDER)

            found[(pri, dist, distname)] = True

        if found:
            dists = list(found.keys())
            dists.sort()
            dists.reverse()
            dists = [(x[0], x[2]) for x in dists]
            debvers = dists[0][1]

    try:
        with open('/etc/debian_version', errors='backslashreplace') as fob:
            verfile = fob.readline().strip()
    except IOError:
        print('Unable to open /etc/debian_version', file=sys.stderr)

    if verfile:
        debinfo += 'Debian Release: ' + verfile + '\n'
    if debvers:
        debinfo += '  APT prefers ' + debvers + '\n'
    if dists:
        # Should wrap this eventually...
        # policystr = pprint.pformat(dists)
        policystr = ', '.join([str(x) for x in dists])
        debinfo += '  APT policy: %s\n' % policystr
    if warn:
        debinfo += warn

    return debinfo


def lsb_release_info():
    return get_command_output('lsb_release -a 2>/dev/null')


def get_arch():
    """Get the architecture of the current system.

    :returns:

        The architecture, e.g. ``"i386"``.

    """
    arch = get_command_output('COLUMNS=79 dpkg --print-architecture 2>/dev/null').strip()
    if not arch:
        un = os.uname()
        arch = un[4]
        arch = re.sub(r'i[456]86', 'i386', arch)
        arch = re.sub(r's390x', 's390', arch)
        arch = re.sub(r'ppc', 'powerpc', arch)
    return arch


def get_multiarch():
    out = get_command_output('COLUMNS=79 dpkg --print-foreign-architectures 2>/dev/null')
    return ', '.join(out.splitlines())


def generate_blank_report(package, pkgversion, severity, justification,
                          depinfo, confinfo, foundfile='', incfiles='',
                          system='debian', exinfo=None, type=None, klass='',
                          subject='', tags='', body='', mode=MODE_EXPERT,
                          pseudos=None, debsumsoutput=None, issource=False,
                          options=None):
    # For now...
    from . import bugreport

    sysinfo = (package not in debbugs.debother and (options and not options.buildd_format))

    # followup is where bugreport expects the notification of the bug reportbug
    # to follow-up, but reportbug pass this information with 'exinfo'
    rep = bugreport.bugreport(package, version=pkgversion, severity=severity,
                              justification=justification, filename=foundfile,
                              mode=mode, subject=subject, tags=tags, body=body,
                              pseudoheaders=pseudos, followup=exinfo, type=type,
                              system=system, depinfo=depinfo, sysinfo=sysinfo,
                              confinfo=confinfo, incfiles=incfiles,
                              debsumsoutput=debsumsoutput, issource=issource)
    return str(rep)


class our_lex(shlex.shlex):
    def get_token(self):
        token = shlex.shlex.get_token(self)
        if token is None or not len(token):
            return token
        if (token[0] == token[-1]) and token[0] in self.quotes:
            token = token[1:-1]
        return token


USERFILE = os.path.expanduser('~/.reportbugrc')
FILES = ('/etc/reportbug.conf', USERFILE)

CONFIG_ARGS = (
    'sendto', 'severity', 'mua', 'mta', 'email', 'realname', 'bts', 'verify',
    'replyto', 'http_proxy', 'smtphost', 'editor', 'debconf', 'justification',
    'sign', 'nocc', 'nocompress', 'dontquery', 'noconf', 'mirrors', 'keyid',
    'headers', 'interface', 'template', 'mode', 'check_available', 'query_src',
    'printonly', 'offline', 'check_uid', 'smtptls', 'smtpuser', 'smtppasswd',
    'paranoid', 'mbox_reader_cmd', 'max_attachment_size', 'listccme',
    'outfile', 'draftpath')


def first_run():
    return not os.path.exists(USERFILE)


def parse_config_files():
    args = {}
    for filename in FILES:
        if os.path.exists(filename):
            try:
                lex = our_lex(open(filename, errors="backslashreplace"), posix=True)
            except IOError as msg:
                continue

            lex.wordchars = lex.wordchars + '-.@/:<>'

            token = lex.get_token()
            while token:
                token = token.lower()
                if token in ('quiet', 'maintonly', 'submit'):
                    args['sendto'] = token
                elif token == 'severity':
                    token = lex.get_token().lower()
                    if token in list(debbugs.SEVERITIES.keys()):
                        args['severity'] = token
                elif token == 'header':
                    args['headers'] = args.get('headers', []) + [lex.get_token()]
                elif token in ('no-cc', 'cc'):
                    args['nocc'] = (token == 'no-cc')
                elif token in ('no-compress', 'compress'):
                    args['nocompress'] = (token == 'no-compress')
                elif token in ('no-list-cc-me', 'list-cc-me'):
                    args['listccme'] = (token == 'list-cc-me')
                elif token in ('no-query-bts', 'query-bts'):
                    args['dontquery'] = (token == 'no-query-bts')
                elif token in ('config-files', 'no-config-files'):
                    args['noconf'] = (token == 'no-config-files')
                elif token in ('printonly', 'template', 'offline'):
                    args[token] = True
                elif token in ('email', 'realname', 'replyto', 'http_proxy',
                               'smtphost', 'editor', 'mua', 'mta', 'smtpuser',
                               'smtppasswd', 'justification', 'keyid',
                               'mbox_reader_cmd', 'outfile', 'draftpath'):
                    bit = lex.get_token()
                    args[token] = bit
                elif token in ('no-smtptls', 'smtptls'):
                    args['smtptls'] = (token == 'smtptls')
                elif token == 'sign':
                    token = lex.get_token().lower()
                    if token in ('pgp', 'gpg'):
                        args['sign'] = token
                    elif token == 'gnupg':
                        args['sign'] = 'gpg'
                    elif token == 'none':
                        args['sign'] = ''
                elif token == 'ui':
                    token = lex.get_token().lower()
                    if token == 'gtk2':
                        token = 'gtk'
                    if token in list(AVAILABLE_UIS.keys()):
                        args['interface'] = token
                elif token == 'mode':
                    arg = lex.get_token().lower()
                    if arg in list(MODES.keys()):
                        args[token] = arg
                elif token == 'bts':
                    token = lex.get_token().lower()
                    if token in list(debbugs.SYSTEMS.keys()):
                        args['bts'] = token
                elif token == 'mirror':
                    args['mirrors'] = args.get('mirrors', []) + [lex.get_token()]
                elif token in ('no-check-available', 'check-available'):
                    args['check_available'] = (token == 'check-available')
                elif token == 'reportbug_version':
                    # Currently ignored; might be used for compat purposes
                    # eventually
                    w_version = lex.get_token().lower()
                elif token in MUA:
                    args['mua'] = MUA[token]
                elif token in ('query-source', 'no-query-source'):
                    args['query_src'] = (token == 'query-source')
                elif token in ('debconf', 'no-debconf'):
                    args['debconf'] = (token == 'debconf')
                elif token in ('verify', 'no-verify'):
                    args['verify'] = (token == 'verify')
                elif token in ('check-uid', 'no-check-uid'):
                    args['check_uid'] = (token == 'check-uid')
                elif token in ('paranoid', 'no-paranoid'):
                    args['paranoid'] = (token == 'paranoid')
                elif token == 'max_attachment_size':
                    arg = lex.get_token()
                    args['max_attachment_size'] = int(arg)
                elif token == 'envelopefrom':
                    token = lex.get_token().lower()
                    args['envelopefrom'] = token
                else:
                    sys.stderr.write('Unrecognized token: %s\n' % token)

                token = lex.get_token()

    return args


def parse_bug_control_file(filename):
    submitas = submitto = None
    reportwith = []
    supplemental = []
    fh = open(filename, errors='backslashreplace')
    for line in fh:
        line = line.strip()
        parts = line.split(': ')
        if len(parts) != 2:
            continue

        header, data = parts[0].lower(), parts[1]
        if header == 'submit-as':
            submitas = data
        elif header == 'send-to':
            submitto = data
        elif header == 'report-with':
            reportwith += data.split(' ')
        elif header == 'package-status':
            supplemental += data.split(' ')

    return submitas, submitto, reportwith, supplemental


def cleanup_msg(dmessage, headers, pseudos, btstype):
    newheaders = []
    collected_pseudoheaders = []
    clean_pseudoheaders = []
    headerre = re.compile(r'^([^:]+):\s*(.*)$', re.I)
    message = ''
    parsing = lastpseudo = True

    # Include the headers that were passed in too!
    for header in headers:
        mob = headerre.match(header)
        if mob:
            newheaders.append(mob.groups())

    # we normalize pseudoheader keys
    def normph(aph):
        return '-'.join([x.capitalize() for x in aph.split('-')])

    accepted_pseudoheaders = [normph(ph) for ph in PSEUDOHEADERS]

    # Get the pseudo-header fields
    for ph in pseudos:
        mob = headerre.match(ph)
        if mob:
            ph = normph(mob.group(1))
            if ph not in accepted_pseudoheaders:
                accepted_pseudoheaders.append(ph)

    # look through the dirty message and extract headers and pseudoheaders
    for line in dmessage.split(os.linesep):
        if parsing:
            # stop trying to parse (pseudo-)headers at the first empty line
            if not line:
                parsing = False
                continue

            mob = headerre.match(line)
            # GNATS and debbugs have different ideas of what a pseudoheader
            # is...
            if mob and ((btstype == 'debbugs' and
                                 normph(mob.group(1)) not in accepted_pseudoheaders) or
                        (btstype == 'gnats' and mob.group(1)[0] != '>')):
                # unrecognized pseudoheaders are turned into headers
                newheaders.append(mob.groups())
                lastpseudo = False
            elif mob:
                # Continuation lines are not supported for pseudoheaders
                lastpseudo = True
                # Normalize pseudo-header for debbugs, leave as is for
                # gnats
                key, value = mob.groups()
                if key[0] != '>':
                    key = normph(key)
                collected_pseudoheaders.append((key, value))
            elif not lastpseudo and len(newheaders) and line[0] == ' ':
                # Assume we have a continuation line
                lastheader = newheaders[-1]
                newheaders[-1] = (lastheader[0], lastheader[1] + '\n' + line)
            else:
                # Discard anything else found in the (pseudo-)header section
                pass
        elif line.strip() != NEWBIELINE:
            message += line + '\n'

    if btstype == 'gnats':
        for header, content in collected_pseudoheaders:
            if content:
                clean_pseudoheaders += ["%s: %s" % (header, content)]
            else:
                clean_pseudoheaders += [header]

        return message, newheaders, clean_pseudoheaders

    # else btstype is debbugs:
    unique_ph = {}
    repeatable_ph = []

    for header, content in collected_pseudoheaders:
        if header in REPEATABLE_PSEUDOHEADERS:
            # repeatables can append
            repeatable_ph += ['%s: %s' % (header, content)]
            continue

        # non-repeatables
        if header == 'X-Debbugs-Cc' and header in unique_ph:
            unique_ph[header] += ', ' + content
        else:
            # for most non-repeatables, the last overwrites the
            # previous
            unique_ph[header] = content

    # sort pseudoheaders
    for header in accepted_pseudoheaders:
        if header in unique_ph:
            clean_pseudoheaders += ['%s: %s' % (header, unique_ph[header])]

    clean_pseudoheaders.extend(repeatable_ph)

    return message, newheaders, clean_pseudoheaders


def launch_mbox_reader(cmd, url, http_proxy, timeout):
    """Runs the command specified by cmd passing the mbox file
    downloaded from url as a parameter. If cmd is None or fails, then
    fallback to mail program."""
    mbox = open_url(url, http_proxy, timeout)
    if mbox is None:
        return
    (fd, fname) = TempFile()
    try:
        for line in mbox.splitlines():
            fd.write(line + '\n')
        fd.close()
        if cmd is not None:
            try:
                cmd = cmd % fname
            except TypeError:
                cmd = "%s %s" % (cmd, fname)
            error = os.system(cmd)
            if not error:
                return
        # fallback
        os.system('mail -f ' + fname)
    finally:
        os.unlink(fname)


def get_running_kernel_pkg():
    """Return the package of the currently running kernel, needed to force
    assignment for 'kernel' package to a real one"""

    system = platform.system()
    release = platform.release()

    if system == 'Linux':
        return 'linux-image-' + release
    elif system == 'GNU/kFreeBSD':
        return 'kfreebsd-image-' + release
    else:
        return None


def exec_and_parse_bugscript(handler, bugscript, runner=os.system):
    """Execute and parse the output of the package bugscript, in particular
    identifying the headers and pseudo-headers blocks, if present"""

    fh, filename = TempFile()
    fh.close()
    rc = runner('LC_ALL=C %s %s %s' % (handler, shlex.quote(bugscript),
                                          shlex.quote(filename)))

    isheaders = False
    ispseudoheaders = False
    isattachments = False
    headers = pseudoheaders = text = ''
    attachments = []
    fp = open(filename, errors="backslashreplace")
    for line in fp.readlines():
        # we identify the blocks for headers and pseudo-h
        if line == '-- BEGIN HEADERS --\n':
            isheaders = True
        elif line == '-- END HEADERS --\n':
            isheaders = False
        elif line == '-- BEGIN PSEUDOHEADERS --\n':
            ispseudoheaders = True
        elif line == '-- END PSEUDOHEADERS --\n':
            ispseudoheaders = False
        elif line == '-- BEGIN ATTACHMENTS --\n':
            isattachments = True
        elif line == '-- END ATTACHMENTS --\n':
            isattachments = False
        else:
            if isheaders:
                headers += line
            elif ispseudoheaders:
                pseudoheaders += line
            elif isattachments:
                attachments.append(line.strip())
            else:
                text += line
    fp.close()
    cleanup_temp_file(filename)

    return (rc, headers, pseudoheaders, text, attachments)


def check_package_name(pkg):
    """Check the package name against Debian Policy:
    https://www.debian.org/doc/debian-policy/ch-controlfields.html#s-f-Source

    Returns True if the package name is valid."""

    pkg_re = re.compile(r'^[a-z0-9][a-z0-9+-\.]+$')

    return True if pkg_re.match(pkg) else False


def get_init_system():
    """Determines the init system on the current machine"""

    init = 'unable to detect'

    if os.path.isdir('/run/systemd/system'):
        init = 'systemd (via /run/systemd/system)'
    elif not subprocess.call('. /lib/lsb/init-functions ; init_is_upstart', shell=True):
        init = 'upstart (via init_is_upstart())'
    elif os.path.isfile('/run/runit.stopit'):
        init = 'runit (via /run/runit.stopit)'
    elif os.path.isdir('/run/openrc'):
        init = 'OpenRC (via /run/openrc)'
        try:
            with open('/proc/1/comm', 'r') as pf:
                init += f', PID 1: {pf.read().strip()}'
        except:
            pass
    elif os.path.isfile('/sbin/init') and not os.path.islink('/sbin/init'):
        init = 'sysvinit (via /sbin/init)'

    return init

def get_lsm_info():
    """Determines the linux security module enabled on the current machine

    Returns None if there is no LSM enabled on the machine or if the state
    cannot be determined."""

    lsminfo = None

    if os.path.exists('/usr/bin/aa-enabled') \
       and (subprocess.call(['/usr/bin/aa-enabled', '--quiet']) == 0):
        lsminfo = 'AppArmor: enabled'

    if os.path.exists('/usr/sbin/selinuxenabled') and (subprocess.call(['/usr/sbin/selinuxenabled']) == 0):
        if lsminfo is None:
            lsminfo = 'SELinux: enabled - '
        else:
            lsminfo += '; SELinux: enabled - '
        enforce_status = subprocess.check_output(['/usr/sbin/getenforce']).decode('ascii')
        lsminfo += 'Mode: %s - ' % enforce_status[:-1]
        with open('/etc/selinux/config', 'r') as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith('SELINUXTYPE='):
                    lsminfo += 'Policy name: %s' % line.split('=')[1][:-1]
                    break

    return lsminfo


def get_kernel_taint_flags():
    """Determines the kernel taint flags"""

    # https://github.com/torvalds/linux/blob/cedc5b6aab493f6b1b1d381dccc0cc082da7d3d8/include/linux/kernel.h#L582
    # this is going to need updating (but maybe not that often)
    TAINT_FLAGS = ['TAINT_PROPRIETARY_MODULE',
                   'TAINT_FORCED_MODULE',
                   'TAINT_CPU_OUT_OF_SPEC',
                   'TAINT_FORCED_RMMOD',
                   'TAINT_MACHINE_CHECK',
                   'TAINT_BAD_PAGE',
                   'TAINT_USER',
                   'TAINT_DIE',
                   'TAINT_OVERRIDDEN_ACPI_TABLE',
                   'TAINT_WARN',
                   'TAINT_CRAP',
                   'TAINT_FIRMWARE_WORKAROUND',
                   'TAINT_OOT_MODULE',
                   'TAINT_UNSIGNED_MODULE',
                   'TAINT_SOFTLOCKUP',
                   'TAINT_LIVEPATCH',
                   'TAINT_AUX',
                   'TAINT_RANDSTRUCT',
    ]

    flags = []

    if os.path.exists('/proc/sys/kernel/tainted'):
        tainted = int(open('/proc/sys/kernel/tainted').read())

        # tainted is an integer representing a bitmask, so logical-AND against the list of
        # flags and if it's a TRUE, then append it to the list of flags enabled
        for i, flag in enumerate(TAINT_FLAGS):
            if tainted & 2**i:
                flags.append(flag)

    return flags


def is_security_update(pkgname, pkgversion):
    """Determine whether a given package is a security update.

    Detection of security update versions works most reliably if the
    package version under investigation is the currently installed
    version.  If this is not the case, the probability of false
    negatives increases.

    Parameters
    ----------
    pkgname : str
        package name
    pkgversion : str
        package version

    Returns
    -------
    bool
        True if there is evidence that this version is a security
        update, otherwise False
    """

    # Check 1:
    # If it does not follow the debXuY version number pattern, it is
    # definitely no security update.
    #
    # This check is not sufficient to detect security updates reliably,
    # since other stable updates also use the same version pattern.
    regex = re.compile(r'(\+|~)deb(\d+)u(\d+)')
    secversion = regex.search(pkgversion)
    if not secversion:
        return False

    # Check 2:
    # If the package comes from the Debian-Security package source, it
    # is definitely a security update.
    #
    # This check does not identify all security updates, since some of
    # them are distributed through the normal channels as part of a
    # stable release update.
    try:
        p = _apt_cache[pkgname]
        if 'Debian-Security' in [o.label for o in
                        p.versions[pkgversion].origins]:
            return True
    except:
        pass

    # Check 3:
    # Inspect the package changelog if it mentions any vulnerability,
    # identified by a CVE number, in the section of the latest version.
    cl = None
    for cl in ['/usr/share/doc/{}/changelog.Debian.gz'.format(pkgname),
               '/usr/share/doc/{}/changelog.gz'.format(pkgname)]:
        if os.path.exists(cl):
            break

    try:
        with gzip.open(cl, 'rt') as f:
            ln = f.readline()
            if pkgversion not in ln:
                raise KeyError

            for ln in f.readlines():
                # stop reading at the end of the first section
                if ln.rstrip() != '' and (ln.startswith(' -- ') or not ln.startswith(' ')):
                    break

                if 'CVE-20' in ln.upper():
                    return True
    except:
        pass

    # guess 'no security update, but normal stable update' by default
    return False
