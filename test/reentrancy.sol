contract reentrancy{

    function myfunc() {
        msg.sender.send(0x1);
    }
}