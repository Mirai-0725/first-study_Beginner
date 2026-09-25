#!/bin/bash
# Django のテスト実行時に作成されるテスト用DB(test_<DB名>)を、アプリ用ユーザーが作成・削除できるようにする。
# MySQL コンテナの初回起動時(データが空のとき)にだけ実行される。
set -e

mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" <<SQL
GRANT ALL PRIVILEGES ON \`test_${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'%';
FLUSH PRIVILEGES;
SQL
