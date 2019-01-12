pragma solidity ^0.4.0;

contract earlypay {
  Main main;
  uint a = 10;
  function PayMain(address _m) {
     main = Main(_m);
  }
  function () payable {
    a = 5;
    if (a > 10) {
        msg.sender.call.value(1)();
    } else {
        msg.sender.call.value(2)();
    }
    a = 9;
  }
}

contract Main {
  function handlePayment(address senderAddress) payable public {
      // senderAddress in this example could be removed since msg.sender can be used directly
  }
}