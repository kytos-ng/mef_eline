#########
Changelog
#########
All notable changes to the MEF_ELine NApp will be documented in this file.

[Unreleased]
************

Added
=====

- Reintroduced Q-in-Q when creating the flows for an EVC.
- Optimize list of circuits filters
- Migrated persistency from kytos/storehouse to MongoDB (integration with pymongo)
- ELineController and DB models
- ``storehouse_to_mongo.py`` script to migrate data from storehouse to MongoDB
- Retries to handle database ``AutoReconnect`` exception.


[2022.1.5] - 2022-02-11
***********************

Fixed
=====

- Adjust default value for `settings.WAIT_FOR_OLD_PATH` since now it measured
  in execution rounds instead of seconds


[2022.1.4] - 2022-02-11
***********************

Fixed
=====
-  Fix UI to keep kytos panel width with default value


[2022.1.3] - 2022-02-11
***********************

Fixed
=====
-  Fix UI to display the scrollbar in the autocomplete results list


[2022.1.2] - 2022-02-03
***********************

Fixed
=====
-  Fix UI to make tag fields optional and editable


[2022.1.1] - 2022-02-03
***********************

Fixed
=====
-  Fix UI list button not re-rendering the content


[2022.1.0] - 2022-01-31
***********************

Added
=====
-  Added utils ``notify_link_available_tags``` function
-  Publish ``kytos/mef_eline.link.available_tags`` event
-  Hooked ``notify_link_available_tags`` when choosing or making vlans available


[2.6.0] - 2021-11-30
********************

Added
=====
- Parametrized ``force`` option as ``True`` when removing flows for reliability


[2.5.1] - 2021-05-28
********************

Fixed
=====
- Fixed UI to list and create EVCs
- Added locks to avoid race conditions


[2.5] - 2021-03-31
******************

Added
=====
- Queue ID can be defined when creating an EVC.
- Method to handle flow mod errors.
- Method to check if two EVCs have a common UNI.
- 2-byte prefix in cookie field.

Changed
=======
- Deployment of EVCs loaded on startup delayed.
- Required versions of python packages updated.
- Removed user VLAN encapsulation.
- EVC id reduced from 16 to 14 bytes.

Fixed
=====
- Thread locks when saving to the storehouse, avoiding race conditions.


[2.4] - 2020-07-23
******************

Added
=====
- Added EVC status check when deploying using schedule.
- Serialize circuit scheduler for storehouse.
- Fix VLAN availability on interfaces after using them.
- Documentation about delete method.
- Added '.travis.yml' to enable Travis CI.
- Added tags decorator to run tests by type and size.
- Install flows when UNIs are in the same switch.

Changed
=======
- Updated HTTP return messages and codes when an error happens.
- Accept EVCs where UNI has no tag.
- Path status now return disabled state if any of its links is disabled.
- Updated method to get the shortest path, now it returns more paths.
- Changed enable/enabled to update _enabled attribute and activate/active to
  update _active attribute.
- Updated OpenApi Models description and documentation.

Deprecated
==========
- Do not create a job when action is not ``create`` or ``remove``.

Removed
=======
- Removed dependencies.

Fixed
=====
- Fixed enable on update EVCs.


[2.3.1] - 2019-03-15
********************

Added
=====
- Scrutinizer running after every push to GitHub repository.
- Linter checking all python code.

Fixed
=====
- Fixed link up/down events from kytos/topology (#99 and #100).
- Load VLANs from storehouse (#101).
- Check path status using kytos/topology (#102).
- Fixed tests to mock call to get links from kytos/topology (#118).

[2.3.0] - 2018-12-14
********************

Added
=====
- Added more API documentation.
- Added EVC flow removal based on cookies.
- Added EVC deletion API method.

Fixed
=====
- Fixed circuit not being deployed.
- Fixed `current_path` changes not being saved on storehouse (#85).
- Fixed storehouse always creating a new box (#91).
- Fixed handling of link up/down events.

[2.2.2] - 2018-10-15
********************

Fixed
=====
- Fixed error when creating a circuit with scheduling and without `start_date`
   (#79 and #80)

[2.2.1] - 2018-09-06
********************
Added
=====
- Added endpoint to allow update circuit informations.
- Added structure to support ci integration: unittests, linter, tox and
  scrutinizer.
- Added some tests for the class already created.
- Added some LinkProtection features:
  - Added method to handle when links goes up or end_maintenance.
  - Added method to handle when links goes down or under_maintenance.
  - When primary_path and backup_path goes down or under_maintenance and
    `dynamic_backup_path` is setted as True a dynamic path is choosed using the
    PathFinder NApp when the primary and backup path is both down or not
    setted.
  - When the primary_path is down and backup_path exists and is UP the circuit
    will change from primary_path to backup_path.
  - When the primary_path change from DOWN to UP the circuits will change to
    the primary_path.
  - When the circuit is disabled the circuit will not be deployed.
  - Added method to looking for links affected was created using the python
    `set` class to be more fast to find the links affected.

Changed
=======
- Change deploy to use primary_path, backup_path or a dynamic_path.
- Improved the Schedule to use advanced python scheduler (APScheduler) library.
Thanks @ajoaoff for recommends this library.
- The attribute circuit_scheduler in the EVC class should have some instances
of CircuitScheduler, this instances will have the information about the
scheduler informations.

Fixed
=====
- Fixed the create circuit method when sending a invalid request
- Fixed some linter warnings.

[2.2.0] - 2018-06-15
********************
Added
=====
- Added EVC class to represent a circuit.
- Added Schedule class to schedule the circuit deploy.
- Added persistence with the NApp kytos/storehouse.

Changed
=======
- Refactor main.py and models.py

Fixed
=====
- Removed duplicated key in openapi.yml

[2.1.0] - 2018-04-20
********************
Added
=====
- Add Schedule class
- Add Mef-Eline component

Changed
=======
- Update openapi.yml
- Update README.rst

[2.0.0] - 2018-03-09
********************
Added
=====
- New /evc endpoint.
- Future endpoint URLs.
- EPL and EVPL support, with VLANs in both endpoints.

Changed
=======
- Method to install flows to the switches.
- List of links now represented by Link objects.

Removed
=======
- Old /circuit endpoints.
