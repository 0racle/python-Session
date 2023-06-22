NAME
====

Session - Wrapper around paramiko for working with client shells

SYNOPSIS
========

```python
import session

try:
    s = session.Session(
        host='branch-rtr-01',
        username='admin',
        password='secret',
    )
except Exception as e:
    print(f"Connection error: {e}")
    exit(1)

for line in s.cmd('show system uptime').splitlines():
    print(line)

s.close()
```
