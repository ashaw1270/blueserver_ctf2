<!DOCTYPE HTML>  
<html>
<head>
<style>
.error {color: #FF0000;}
</style>
</head>
<body>  

<?php
// define variables and set to empty values
$userErr = $passErr = "";
$error = FALSE;
$user = $pass = "";

if ($_SERVER["REQUEST_METHOD"] == "GET") {
  if (empty($_GET["user"])) {
    $error = TRUE;
    $nameErr = "Username is required";
  } else {
    $user = test_input($_GET["user"]);
   }
  
  if (empty($_GET["pass"])) {
    $passErr = "Password is required";
    $error = TRUE;
  } else {
    $pass = test_input($_GET["pass"]);
 }

 if (!$error)
 {
     $mysqli = new mysqli("localhost","root", "root", "bank");
     
     // Check connection
     if ($mysqli -> connect_errno) {
       echo "Failed to connect to MySQL: " . $mysqli -> connect_error;
       exit();
    }
     // Perform query
    $stmt = "select pass from users where name='" . $user . "'";
    $result = $mysqli -> query($stmt);
    $obj = $result->fetch_object();

    if ($pass == $obj->pass)
    { 
      echo "Logged in";
      setcookie('user', $user);
    }
    else
    {
      $error = TRUE;
      $passErr= "Wrong password";
    }

    $mysqli -> close();

 }

}
    
function test_input($data) {
  $data = trim($data);
  $data = stripslashes($data);
  return $data;
}
?>

<h2>PHP Form Validation Example</h2>
<p><span class="error">* required field</span></p>
<form method="get" action="index.php">
  Username: <input type="text" user="user" value="<?php echo $user;?>">
  <span class="error">* <?php echo $userErr;?></span>
  <br><br>
  Password: <input type="text" name="pass" value="<?php echo $pass;?>">
  <span class="error">* <?php echo $passErr;?></span>
  <br><br>
  <input type="submit" name="submit" value="Submit">  
</form>

<?php
echo "<h2>Your Input:</h2>";
echo $user;
echo "<br>";
echo $pass;
?>

</body>
