Developer Guide
===============

This section details some essential points to contribute to the code base.
Don't hesitate to ask for advice on the `mailing list
<https://sympa-2.sipr.ucl.ac.be/sympa/info/ipmininet>`_,
to report bugs as Github issues and to contribute through Github pull requests.

Project conventions
-------------------

- **Workflow:** GitHub Flow. One short-lived branch per change, opened as a
  pull request, merged to ``master`` with a rebase merge. ``master`` is always
  releasable.
- **Commits:** Conventional Commits (``type(scope): subject``), imperative
  mood, signed.
- **Versioning:** bump ``pyproject.toml`` only when cutting a release.
  ``fix`` → PATCH, ``feat`` → MINOR, breaking changes → MAJOR. Additive and
  backwards-compatible changes without significant new functionality are
  PATCH.
- **Changelog:** GitHub release notes, assembled from merged pull-request
  titles.

Setting up the development environment
--------------------------------------

To develop a new feature, you have to install IPMininet from source
in development mode.

First get the source code of your fork:

.. code-block:: bash

    $ git clone <your-fork-url>
    $ cd ipmininet

Then, install your version of IPMininet in development mode:

.. code-block:: bash

    $ uv sync --group dev

Finally, you can install all the daemons:

.. code-block:: bash

    $ sudo python -m ipmininet.install -af

Understanding IPMininet workflow
--------------------------------

The following code creates, starts and stops a network:

.. code-block:: python

    from ipmininet.ipnet import IPNet
    from ipmininet.cli import IPCLI
    from ipmininet.iptopo import IPTopo

    class MyTopology(IPTopo):
        # [...]

    topo = MyTopology()  # Step 1
    net = IPNet(topo=topo)  # Steps 2 to 5
    try:
        net.start() # Steps 6 to 8
    finally:
        net.stop()  # Step 9

During the execution of this code, IPMininet goes through the following steps
(detailed in the following sections):

1. Instantiation of the topology and application of the overlays
2. Instantiation of all the devices classes
3. Instantiation of the daemons
4. Addressing
5. Call of the post_build method
6. Finalization and validation of daemon configurations
7. Start of daemons
8. Insertion of the default routes
9. Cleanup of the network

1. Instantiation of the topology and application of the overlays
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The instantiation of the Topology triggers a call to its
:meth:`~ipmininet.iptopo.IPTopo.build` method. This method is where users
define the topology: switches, routers, links, hosts,... But at that time,
every node is actually a node name, not instances of Switches, Routers,
IPHosts,...

The node and link options are stored in the :class:`~ipmininet.iptopo.IPTopo`
object and a instance of ``mininet.topo.MultiGraph`` stores the
interconnections between nodes.

At the end of the build method, overlays are applied
(:meth:`ipmininet.overlay.Overlay.apply`) and checked for consistency
(:meth:`ipmininet.overlay.Overlay.check_consistency`).

2. Instantiation of all the devices classes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each device class (e.g., routers or hosts) is actually instantiated based
on the graph and the parameters stored in the :class:`~ipmininet.iptopo.IPTopo`
instance (in :meth:`ipmininet.ipnet.IPNet.buildFromTopo`). From this point, a
network namespace is created for each device with interfaces linking to the
other namespaces as defined in the topology.
It becomes possible to execute commands on a given device.

3. Instantiation of the daemons
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When instantiating each router and each host, their daemons are also
instantiated and options parsed. However the daemon configurations are not
built yet.

4. Addressing
^^^^^^^^^^^^^

After creating all the devices and their interfaces,
:meth:`~ipmininet.ipnet.IPNet.build` create one
:class:`~ipmininet.ipnet.BroadcastDomain` by IP broadcast domain. That is,
two router or host interfaces belong to the same BroadcastDomain if they are
directly connected or indirectly connected through only switches or hubs.

IPMIninet then allocates the same IP prefix on interfaces in the same IP
broadcast domain. At the end of this step, every interface has its IPv4
and/or IPv6 addresses assigned (if auto-allocation was not disabled).

5. Call of the post_build method
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Now, all the devices are created and that they have their IP addresses
assigned. Users may need this information before adding other elements to
the network like IPv6 Segment Routing rules
(see :ref:`Using IPv6 Segment Routing`).
Therefore the method :meth:`~ipmininet.iptopo.IPTopo.post_build` is called.

6. Finalization and validation of the daemon configurations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In each router and each host, their daemon configurations are
built (through each daemon's
:meth:`~ipmininet.router.config.base.Daemon.build` method).

Then the built configuration is used to fill in the templates and create the
actual configuration files of each daemons (in the
:meth:`~ipmininet.router.config.base.Daemon.render` method).

When all configurations are built, the configuration is checked by running
the dry run command specified by the
:meth:`~ipmininet.router.config.base.Daemon.dry_run` property of each deamon.
If one of the dry runs fails, the network starting is aborted.

7. Start of the daemons
^^^^^^^^^^^^^^^^^^^^^^^

From this point, all the daemon configuration files are generated and they
were checked. Thus, the next step is to start each daemon in its respective
network namespace. The command line used to run the daemon is specified by the
:meth:`~ipmininet.router.config.base.Daemon.startup_line` property.

8. Insertion of the default routes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For each host, a default route is added to one of the router in the same IP
broadcast domain. This behavior is disabled if a default route was harcoded
in the options or if router advertisements are enabled in the IP broadcast
domain.

9. Cleanup of the network
^^^^^^^^^^^^^^^^^^^^^^^^^

This cleans up all the network namespaces defined for the devices as well as
killing all the daemon processes started. By default, the configuration files
are removed (except when the ``ipmininet.DEBUG_FLAG`` is set to ``True``).

Running the tests
-----------------

The `pytest <https://docs.pytest.org/en/latest/index.html>`_ framework is used
for the test suite. The suite is end-to-end and requires root and the daemons
to be installed and in PATH. Run it in parallel as CI does:

.. code-block:: bash

    sudo scripts/run-tests-parallel.sh

Or run a single test by passing options to pytest:

.. code-block:: bash

    sudo uv run pytest ipmininet/tests/test_sshd.py --fulltrace

Some tests are skipped conditionally based on the environment (e.g. running
as a non-root user, or a missing routing daemon). See the "Test-skip policy"
comment at the top of ``ipmininet/tests/__init__.py`` for the full matrix and
reasons; skipped tests and their reasons are shown with ``pytest -rs``.

Coverage and code-quality gates
-------------------------------

- CI measures **branch coverage** (``[tool.coverage]`` in ``pyproject.toml``
  is the single source of truth). PRs run a cheap rootless coverage pass;
  ``master`` enforces the full-suite gate with
  ``coverage report --fail-under``. Reports (``coverage.xml`` + ``htmlcov/``)
  are uploaded as workflow artifacts and to Codecov.
- Run coverage locally with ``COVERAGE=1 scripts/run-tests-parallel.sh`` (as
  root), or on the rootless tests directly with
  ``uv run pytest --cov=ipmininet ipmininet/tests/test_pure.py``.
- Code duplication is capped by ``scripts/check-duplicates.sh`` (pylint
  ``duplicate-code``) against the ``duplication_max`` baseline in
  ``pyproject.toml``; CI runs it in the ``rootless`` job.

Writing reliable tests
----------------------

The test suite runs end-to-end against real daemons (FRRouting, named,
ExaBGP, ...) in parallel CI workers, so asynchronous effects (daemon startup,
routing convergence, DNS zone transfer, packet capture) are subject to load.
Follow these rules to keep the suite deterministic:

- **Never wait a fixed wall-clock amount of time for an asynchronous
  effect.** A fixed ``time.sleep()`` is either too short (flaky under load)
  or too long (slow for no reason). Instead, poll for the *observable
  effect* until it appears, with a hard timeout, using the
  ``wait_until(predicate, timeout=..., interval=..., description=...)``
  helper in ``ipmininet/tests/utils.py`` (check-then-sleep, fails the test
  with a descriptive error on timeout). The ``description`` may be a callable
  so the failure can include the last observed state.
- **Reuse the existing poll helpers** built on ``wait_until`` rather than
  hand-rolling loops: ``assert_routing_table``, ``assert_dns_record``,
  ``assert_stp_state``, ``assert_connectivity``,
  ``check_tcp_connectivity``, ``traceroute``/``assert_path``.
- **Assert before you index.** Check that a key/row exists *before*
  dereferencing it; otherwise a not-ready state surfaces as a bare
  ``KeyError``/``IndexError`` instead of the intended assertion message.
- **Bound every poll loop.** Never use ``while t != ...`` as a loop sentinel
  (a skipped increment runs forever); prefer ``while t < bound`` or
  ``wait_until``.
- **Wait for the effect's own notification, not for a proxy of it.** A
  process being alive (or a file existing) does not mean the effect has
  landed. This is subtle: a freshly started ``tshark`` prints "Capturing
  on ..." *before* the capture is functionally live, so even that message is
  a proxy. The reliable notification that a capture is live is its output
  file growing past the header (packets are being written); wait for that by
  probing until every node's capture has grown, then send the measurement and
  stop the capture with ``SIGINT`` (which flushes) before asserting in the
  read-back that the measurement actually landed. Beware of nodes that never
  see the measurement (off-path hosts): never require them to record it.
  When the measurement has to be spread over several probes, the analysis
  must group the observations per probe (they are well apart in time) or the
  path repeats once per probe.
- **Probes must not perturb the thing under test.** A readiness probe can
  consume the very resource being measured (e.g. ``nc -z`` consumes the single
  connection that an ``iperf3 --one-off`` server accepts, so the real client
  gets nothing). Prefer a passive observation such as ``ss -ltn``.
- **Size poll timeouts to the protocol's worst case, not the median.** If a
  daemon is documented to delay its actions by up to N seconds, the poll
  timeout must exceed N. Raise the per-test ceiling with
  ``@pytest.mark.timeout(...)`` where needed.
- **Avoid shared hard-coded paths and ports.** Prefer per-test temporary
  files over fixed ``/tmp/`` paths that leak across parametrized cases.
- **Let timeouts fail fast.** ``pytest-timeout`` is configured with a
  600-second per-test limit, so a stuck test fails instead of eating the CI
  budget; keep the ``timeout`` of poll helpers comfortably below it and only
  raise the per-test limit with ``@pytest.mark.timeout(...)`` for the rare
  test whose protocol requires more.
- **Schedule long-waiting tests first.** ``scripts/run-tests-parallel.sh``
  lists the slow modules first and runs under ``--dist=loadscope`` (one module
  per worker at a time), so a module that mostly *waits* overlaps with the
  CPU-bound work of the modules behind it. A waiting test is cheap to
  co-schedule, so order by waiting time, not by CPU time.

The full flaky-pattern catalog used by reviewers is in
``.tmp/FLAKY_REVIEW.md`` (local scratch, not committed).


Building the documentation
--------------------------

First, install the documentation build dependencies (the ``docs`` uv
dependency group) at the root of the repository:

.. code-block:: bash

    uv sync --group docs

Then you can generate the html documentation
in the folder ``docs/_build/html/`` with:

.. code-block:: bash

    uv run --group docs make -C docs html

The documentation build is covered by CI (see ``.github/workflows/docs.yaml``),
which builds with ``sphinx-build -W`` so warnings are treated as errors. The
markdown included from the example topologies is pulled in through
``sphinx-mdinclude``, which pins ``mistune`` to ``>=3,<4``; do not relax that
constraint without also replacing ``sphinx-mdinclude``.

The examples in the documentation can also be tested when changing the code base
with the following command:

.. code-block:: bash

    sudo uv run --group docs make -C docs doctest

.. _contribute_example:

Adding a new example
--------------------

When adding a new example of topology to IPMininet,
you have to perform the following tasks:

- Create a new ``IPTopo`` subclass in the folder ``ipmininet/examples/``.
- Add the new class to the dictionary ``TOPOS``
  of ``ipmininet/examples/__main__.py``.
- Document its layout in the ``build()`` method docstring.
- Document the example in ``ipmininet/examples/README.md``.
- Add a test to check the correctness of the example.

Adding a new daemon
-------------------

When adding a new daemon to IPMininet, you have to perform the following tasks:

- Create a new `mako template <https://www.makotemplates.org/>`_
  in the folder ``ipmininet/router/config/templates/`` or
  ``ipmininet/host/config/templates/`` for the daemon configuration.
- Create a new ``RouterDaemon`` or ``HostDaemon`` subclass in the folder ``ipmininet/router/config/``
  or ``ipmininet/host/config/``.
  The following things are required in this new subclass:

  * Set the class variable ``NAME`` with a unique name.
  * Set the class variable ``KILL_PATTERNS`` that lists
    all the process names that have to be cleaned
    if a user uses the cleaning command in :ref:`getting_started_cleaning`.
  * Extend the property ``startup_line`` that gives the command line
    to launch the daemon.
  * Extend the property ``dry_run`` that gives the command line
    to check the generated configuration.
  * Extend the method ``set_defaults()`` to set default configuration values
    and document them all in the method docstring.
  * Extend the method ``build()`` to set the ConfigDict object
    that will be fed to the template.
  * Declare the daemon and its helper classes
    in ``ipmininet/router/config/__init__.py`` or ``ipmininet/host/config/__init__.py``.

- Add at least one example for the users (see :ref:`contribute_example`).
- Implement the tests to prove the correct configuration of the daemon.
- Update the setup of IPMininet to install the new daemon by updating
  ``ipmininet/install/__main__.py`` and ``ipmininet/install/install.py``.
- Document the daemon and its configuration options
  in the sphinx documentation in ``docs/daemons.rst``.

Adding a new overlay
--------------------

An overlay is a way to change options of multiple nodes or links in a single
code. For instance, defining an :class:`~ipmininet.router.config.bgp.AS` object
will add the defined as number in each node declared in the AS.

When adding a new overlay to IPMininet, you have to perform the following tasks:

- Create a new ``Overlay`` subclass in the most appropriate file. For
  instance, BGP overlays like :class:`~ipmininet.router.config.bgp.AS` are in
  the BGP daemon file.
  The following methods are potentially useful to override in this new subclass:

  .. automethod:: ipmininet.overlay.Overlay.apply
      :noindex:
  .. automethod:: ipmininet.overlay.Overlay.check_consistency
      :noindex:
- Add the new subclass in the dictionary ``OVERLAYS`` of class
  :class:`~ipmininet.iptopo.IPTopo`. This enables users to use ``self.addX()``
  in the build method of their topology subclass with ``X`` being the name of
  your new overlay.
- Add at least one example for the users (see :ref:`contribute_example`).
- Implement the tests to prove the correctness of the overlay.
- Document the overlay and its configuration options in the sphinx
  documentation.
