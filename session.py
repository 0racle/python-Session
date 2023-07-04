import re
import io
import socket
import paramiko
import warnings

warnings.filterwarnings(action="ignore", module=".*paramiko.*")


class ConnectionFailure(Exception):
    pass


class ReadTimeout(Exception):
    pass


class BufferFull(Exception):
    pass


# ANSI Control Sequence Introducer sequence
ansi_csi_seq = "".join([
    "\x1b",          # ESC
    "\[",            # Left Square Bracket
    "[\x30-\x3f]*",  # Parameter Bytes     -> [0123456789:;<=>?]
    "[\x20-\x2f]*",  # Intermediate Bytes  -> [ !"#$%&'()*+,-./]
    "[\x40-\x7e]",   # Final Byte          -> [@A-Z[\]^_`a-z{|}~] 
])

# Carriage Return with no Line Feed
cr_without_lf = "\x0d(?!\x0a)"

clean = re.compile("|".join([ansi_csi_seq, cr_without_lf]))


def ansi_clean(string):
    return re.sub("\x0d\x0a", "\x0a", clean.sub("", string))


class Session:
    bufsize = 1048576
    blksize = 4096
    buf = ""

    def __init__(self, host, username, password, port=22, timeout=10,
                 prompt=re.compile(r".*[#>]\s*$"), echo=False, log=None,
                 term="vt100", rows=20000, cols=160, encoding="utf8"):

        self.host = host
        self.port = port
        self.timeout = timeout
        self.prompt = prompt
        self.echo = echo
        self.term = term
        self.rows = rows
        self.cols = cols
        self.encoding = encoding

        self.log = log
        if log is not None and not isinstance(log, io.IOBase):
            self.log = open(str(log), "w", encoding=encoding, newline="\r\n")

        try:
            self.open(username, password)
        except socket.timeout:
            raise ConnectionFailure("Connection timed out") from None
        except paramiko.ssh_exception.NoValidConnectionsError:
            raise ConnectionFailure("Connection refused") from None
        except paramiko.ssh_exception.AuthenticationException:
            raise ConnectionFailure("Authentication failed") from None

        try:
            pre, bufmatch = self.waitfor(pattern=self.prompt)
            self.last_prompt = bufmatch
        except ReadTimeout:
            raise ReadTimeout("Timed out waiting for prompt") from None


    def __repr__(self):
        return f'{self.__class__.__qualname__}(host="{self.host}")'


    def __del__(self):
        self.close()


    def open(self, uname, pword):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.host,
            port=self.port,
            username=uname,
            password=pword,
            timeout=self.timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        self.client = client
        self.shell = client.invoke_shell(
            term=self.term, width=self.cols, height=self.rows
        )
        self.shell.settimeout(self.timeout)


    def close(self):
        if self.log:
            self.log.close()
        try:
            self.shell.close()
        except:
            pass


    def send(self, data):
        sent = self.shell.send(data)
        while not self.shell.recv_ready():
            pass
        return sent


    def put(self, text):
        return self.send(text + "\n")


    def read(self):
        if len(self.buf) > 0:
            buf = self.buf
            self.buf = ""
            return buf
        try:
            chunk = self.shell.recv(self.blksize)
        except socket.timeout:
            raise ReadTimeout("Timed out") from None
        string = chunk.decode(self.encoding, errors="ignore")
        text = ansi_clean(string)
        if self.log:
            if 'b' in self.log.mode:
                self.log.write(chunk)
            else:
                self.log.write(text)
        return text


    def readline(self):
        buf = ""
        while True:
            chunk = self.read()
            if len(buf + chunk) > self.bufsize:
                raise BufferFull("Input buffer full") from None
            buf += chunk
            m = re.search("\x0a", buf)
            if m:
                line = buf[: m.start()]
                self.buf = buf[m.end() :]
                return line


    def waitfor(self, *, pattern):
        if isinstance(pattern, str):
            pattern = re.compile(re.escape(pattern))
        buf = ""
        while True:
            chunk = self.read()
            if len(buf + chunk) > self.bufsize:
                raise BufferFull("Input buffer full") from None
            buf += chunk
            m = pattern.search(buf)
            if m:
                pre = buf[: m.start()]
                bufmatch = buf[m.start() : m.end()]
                self.buf = buf[m.end() :]
                return (pre, bufmatch)


    def recv(self):
        while True:
            chunk = self.read()
            yield chunk
            last = chunk.splitlines()[-1]
            if self.prompt.search(last):
                break


    def cmd(self, command):
        self.buf = ""
        while self.shell.recv_ready():
            self.read()
        self.put(command)
        try:
            pre, bufmatch = self.waitfor(pattern=self.prompt)
        except ReadTimeout:
            raise ReadTimeout("Timed out waiting for input") from None
        if self.echo:
            output = self.last_prompt + pre
        else:
            output = re.sub(".*\x0a", "", pre, count=1)
        self.last_prompt = bufmatch
        return output
