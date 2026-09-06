Installation
============


IPMininet needs at minimum:

- Python_ (with pip) **3.12+**
- Mininet_

IPMininet needs some daemon executables to be installed
and accessible through the PATH environment variable:

- FRRouting_ daemons: zebra, ospfd, ospf6d, bgpd, pimd
- RADVD_
- SSHD_

.. _Python: https://www.python.org
.. _Mininet: http://www.mininet.org
.. _FRRouting: https://frrouting.org
.. _RADVD: http://www.litech.org/radvd
.. _SSHD: https://www.openssh.com

You can either download them by hand or rely
on one the following methods:

Virtual Machine
---------------

We maintain a `vagrant box`_ packaged with all the daemons.
To use it, first install `Vagrant`_ and `Virtualbox`_
and then, execute the following commands:

.. code-block:: bash

    $ vagrant init ipmininet/ubuntu-20.04
    $ vagrant up

This will create the VM. To access the VM with SSH, just issue the
following command in the same directory as the two previous one:

.. code-block:: bash

    $ vagrant ssh

.. _vagrant box: https://app.vagrantup.com/ipmininet/boxes/ubuntu-20.04
.. _Vagrant: https://www.vagrantup.com/downloads.html
.. _Virtualbox: https://www.virtualbox.org/wiki/Downloads

Manual installation
-------------------

You can download and install IPMininet.
You can change the installed version by replacing the version tag in the following command:

.. code-block:: bash

    $ sudo pip install --upgrade git+https://github.com/mimi-net/ipmininet.git@v1.3.0

Then, you can install all the daemons:

.. code-block:: bash

    $ sudo python -m ipmininet.install -af

You can choose to install only a subset of the daemons
by changing the options on the installation script.
For the option documentations, use the ``-h`` option.

The installer provisions FRRouting **10.7.1** (built from source) and installs
ExaBGP **5.0.13** via pip. IPMininet generates FRR configs through the mgmtd
backend introduced in FRR 9, so an environment provisioned by an older
IPMininet must be **re-provisioned** (``sudo python -m ipmininet.install -af``)
after upgrading the library, or the daemon startup checks will fail.

.. _documentation: http://mininet.org/download/
