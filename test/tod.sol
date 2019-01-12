contract tod {
    uint public flag;

    function update_flag(uint _flag) {
        flag = _flag;
    }

    function myfunc() {
        if (flag == 0) {
            msg.sender.send(0x1);
        } else {
            msg.sender.send(0x2);
        }
    }
}