contract mis_exception {
    //aka callstack attack

    function myfunc() {
        msg.sender.send(0x1);
    }
}