# IPMininet

[![Pypi Version](https://img.shields.io/pypi/v/ipmininet.svg)](https://pypi.python.org/pypi/ipmininet/)
[![Documentation Status](https://readthedocs.org/projects/ipmininet/badge/?version=latest)](http://ipmininet.readthedocs.io/?badge=latest)
[![Code Coverage](https://codecov.io/gh/mimi-net/ipmininet/branch/master/graph/badge.svg)](https://codecov.io/gh/mimi-net/ipmininet)

This is a python library, extending [Mininet](http://mininet.org), in order
to support emulation of (complex) IP networks. As such it provides new classes,
such as Routers, auto-configures all properties not set by the user, such as
IP addresses or router configuration files, ...

The latest user documentation is available on
https://ipmininet.readthedocs.io/

Requires Python 3.12+ and FRRouting 10.7+ (the generated FRR configs use the
mgmtd backend introduced in FRR 9). Install or re-provision the daemons with
`sudo python -m ipmininet.install -af`; see the installation docs.
