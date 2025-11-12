SERVER=$1
USER=$2
PASS=$3
COOKIE_FILE=cookie.txt

if [ -z "$SERVER" ] || [ -z "$USER" ] || [ -z "$PASS" ]; then
  echo "Usage: $0 <server> <username> <password>"
  exit 1
fi

echo "== Registering user =="
curl -i "http://$SERVER/register.php?user=$USER&pass=$PASS"
echo -e "\n"

echo "== Logging in =="
curl -i -c $COOKIE_FILE "http://$SERVER/login.php?user=$USER&pass=$PASS"
echo -e "\n"

echo "== Displaying current balance (before deposit)  =="
curl -i -b $COOKIE_FILE "http://$SERVER/manage.php?action=balance"

echo "== Depositing 100 =="
curl -i -b $COOKIE_FILE "http://$SERVER/manage.php?action=deposit&amount=100"
echo -e "\n"

echo "== Displaying current balance (after deposit) ==" 
curl -i -b $COOKIE_FILE "http://$SERVER/manage.php?action=balance"

echo "== Withdrawing 50 =="
curl -i -b $COOKIE_FILE "http://$SERVER/manage.php?action=withdraw&amount=50"
echo -e "\n"

echo "== Withdrawing amount > balance current balance  ==" 
curl -i -b $COOKIE_FILE "http://$SERVER/manage.php?action=withdraw&amount=100"
echo -e "\n"

echo "== Closing account =="
curl -s -b $COOKIE_FILE "http://$SERVER/manage.php?action=close"
echo -e "\n"

echo "== Attempting to login with closed account =="
curl -i -c $COOKIE_FILE "http://$SERVER/login.php?user=$USER&pass=$PASS"
echo -e "\n"

