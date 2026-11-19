# Third-party notices

This repository includes or bundles the following third-party software.

## JDBC drivers

Shipped in `ignition/config/resources/core/ignition/database-driver/` as part
of the Ignition gateway configuration. Each is unmodified and is distributed
under its own licence:

| Driver | Licence | Source |
|---|---|---|
| PostgreSQL JDBC 42.7.2 | BSD-2-Clause | https://github.com/pgjdbc/pgjdbc |
| MariaDB Connector/J 3.3.3 | LGPL-2.1 | https://github.com/mariadb-corporation/mariadb-connector-j |
| MySQL Connector/J 9.6.0 | GPL-2.0 with the Universal FOSS Exception | https://github.com/mysql/mysql-connector-j |
| Microsoft JDBC Driver for SQL Server 9.4.0 | MIT | https://github.com/microsoft/mssql-jdbc |

The full licence text of each is inside its jar, and the source for each
version is available at the link above.

## Other content

* **Ignition** gateway configuration, the builtin icon set under
  `ignition/config/resources/core/ignition/images/Builtin/`, and the Ignition
  and Inductive Automation logos are the property of Inductive Automation.
* **Roboto** is loaded from Google Fonts at runtime (Apache-2.0), not bundled.
* The demo inbox under `services/mailpit/gmail/` is a look-alike mock-up for
  showing alarm emails on stage. It is not affiliated with or endorsed by
  Google. Gmail is a trademark of Google LLC.
* **Mailpit** (MIT) and **YouTrack** (JetBrains) run from their own published
  container images; neither is redistributed here beyond YouTrack's seed data.
