Overview
========

This Network Application is part of the Kytos-NG project.

|Stable| |Tag| |License| |Build| |Coverage| |Quality|


.. attention::

    THIS NAPP IS STILL EXPERIMENTAL AND IT'S EVENTS, METHODS AND STRUCTURES MAY
    CHANGE A LOT ON THE NEXT FEW DAYS/WEEKS, USE IT AT YOUR OWN DISCERNEMENT

This Napp allows a user to create a point to point L2 Ethernet Virtual Circuit.

Features
========
- REST API to create/modify/delete circuits;
- REST API to create/modify/delete circuit scheduling;
- list of circuits in memory and also synchronized to a permanent storage;
- circuits can be installed at time of request or have an installation schedule;
- circuits can use a predefined path or find a dynamic path;
- the NApp will move circuits to another path in case of a link down;
- web UI for circuits management.


Requirements
============
- kytos/flow_manager
- kytos/pathfinder
- kytos/topology
- amlight/sndtrace_cp


.. TAGs

.. |Stable| image:: https://img.shields.io/badge/stability-stable-green.svg
   :target: https://github.com/kytos-ng/mef_eline
.. |License| image:: https://img.shields.io/github/license/kytos-ng/kytos.svg
   :target: https://github.com/kytos-ng/mef_eline/blob/master/LICENSE
.. |Build| image:: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/badges/build.png?b=master
   :alt: Build status
   :target: https://scrutinizer-ci.com/g/kytos-ng/kytos/?branch=master
.. |Coverage| image:: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/badges/coverage.png?b=master
   :alt: Code coverage
   :target: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/
.. |Quality| image:: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/badges/quality-score.png?b=master
   :alt: Code-quality score
   :target: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/
.. |Tag| image:: https://img.shields.io/github/license/kytos-ng/kytos.svg
   :target: https://github.com/kytos-ng/mef_eline
