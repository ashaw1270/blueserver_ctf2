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
$actionErr = "";
$error = FALSE;
$user = $pass = "";
$amount = 0;

$user=$_COOKIE['user'];
if ($_SERVER["REQUEST_METHOD"] == "GET") {
  if (empty($_GET["action"])) {
    $error = TRUE;
    $actionrErr = "Action is required";
  } else {
    $action = test_input($_GET["action"]);
    if ($action == "deposit" || $action == "withdraw")
    {
       if (empty($_GET["amount"])) {
       $error = TRUE;
       $amountErr = "Amount is required";
       }
       else
       { 
          $amount = $_GET["amount"];
       }
   }
  }

 if (!$error)
 {
     echo "User $user";
     $mysqli = new mysqli("localhost","root", "root", "bank");
     
     // Check connection
     if ($mysqli->connect_errno) {
       echo "Failed to connect to MySQL: " . $mysqli -> connect_error; 
       exit();
    }
     // Perform query
    $stmt = "select balance from users where name='" . $user . "'";
    $result = $mysqli -> query($stmt);
    $obj = $result->fetch_object();
    $balance = $obj->balance;
    if ($action == "withdraw")
    {
        $balance -= $amount;
    }
    if ($action == "deposit")
    {
        $balance += $amount;
    }
    echo "Balance=" . $balance;
    $stmt = "update users set balance=" . $balance . " where name='" . $user . "'";
    $mysqli -> query($stmt);
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
  Action: <input type="text" action="balance" value="<?php echo $action;?>">
  <span class="error">* <?php echo $actionErr;?></span>
  <br><br>
    Amount: <input type="text" amount="0" value="<?php echo $amount;?>">
  <span class="error">* <?php echo $amountErr;?></span>
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
