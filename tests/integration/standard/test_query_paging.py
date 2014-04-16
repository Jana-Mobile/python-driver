# Copyright 2013-2014 DataStax, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from tests.integration import PROTOCOL_VERSION

import logging
log = logging.getLogger(__name__)

try:
    import unittest2 as unittest
except ImportError:
    import unittest # noqa

from itertools import cycle, count
from threading import Event

from cassandra.cluster import Cluster
from cassandra.concurrent import execute_concurrent
from cassandra.policies import HostDistance
from cassandra.query import SimpleStatement


class QueryPagingTests(unittest.TestCase):

    def setUp(self):
        if PROTOCOL_VERSION < 2:
            raise unittest.SkipTest(
                "Protocol 2.0+ is required for BATCH operations, currently testing against %r"
                % (PROTOCOL_VERSION,))

        self.cluster = Cluster(protocol_version=PROTOCOL_VERSION)
        self.cluster.set_core_connections_per_host(HostDistance.LOCAL, 1)
        self.session = self.cluster.connect()
        self.session.execute("TRUNCATE test3rf.test")

    def test_paging(self):
        statements_and_params = zip(cycle(["INSERT INTO test3rf.test (k, v) VALUES (%s, 0)"]),
                                    [(i, ) for i in range(100)])
        execute_concurrent(self.session, statements_and_params)

        prepared = self.session.prepare("SELECT * FROM test3rf.test")

        for fetch_size in (2, 3, 7, 10, 99, 100, 101, 10000):
            self.session.default_fetch_size = fetch_size
            self.assertEqual(100, len(list(self.session.execute("SELECT * FROM test3rf.test"))))

            statement = SimpleStatement("SELECT * FROM test3rf.test")
            self.assertEqual(100, len(list(self.session.execute(statement))))

            self.assertEqual(100, len(list(self.session.execute(prepared))))

    def test_async_paging(self):
        statements_and_params = zip(cycle(["INSERT INTO test3rf.test (k, v) VALUES (%s, 0)"]),
                                    [(i, ) for i in range(100)])
        execute_concurrent(self.session, statements_and_params)

        prepared = self.session.prepare("SELECT * FROM test3rf.test")

        for fetch_size in (2, 3, 7, 10, 99, 100, 101, 10000):
            self.session.default_fetch_size = fetch_size
            self.assertEqual(100, len(list(self.session.execute_async("SELECT * FROM test3rf.test").result())))

            statement = SimpleStatement("SELECT * FROM test3rf.test")
            self.assertEqual(100, len(list(self.session.execute_async(statement).result())))

            self.assertEqual(100, len(list(self.session.execute_async(prepared).result())))

    def test_paging_callbacks(self):
        statements_and_params = zip(cycle(["INSERT INTO test3rf.test (k, v) VALUES (%s, 0)"]),
                                    [(i, ) for i in range(100)])
        execute_concurrent(self.session, statements_and_params)

        prepared = self.session.prepare("SELECT * FROM test3rf.test")

        for fetch_size in (2, 3, 7, 10, 99, 100, 101, 10000):
            self.session.default_fetch_size = fetch_size
            future = self.session.execute_async("SELECT * FROM test3rf.test")

            event = Event()
            counter = count()

            def handle_page(rows, future, counter):
                for row in rows:
                    counter.next()

                if future.has_more_pages:
                    future.start_fetching_next_page()
                else:
                    event.set()

            def handle_error(err):
                event.set()
                self.fail(err)

            future.add_callbacks(callback=handle_page, callback_args=(future, counter), errback=handle_error)
            event.wait()
            self.assertEquals(counter.next(), 100)

            # simple statement
            future = self.session.execute_async(SimpleStatement("SELECT * FROM test3rf.test"))
            event.clear()
            counter = count()

            future.add_callbacks(callback=handle_page, callback_args=(future, counter), errback=handle_error)
            event.wait()
            self.assertEquals(counter.next(), 100)

            # prepared statement
            future = self.session.execute_async(prepared)
            event.clear()
            counter = count()

            future.add_callbacks(callback=handle_page, callback_args=(future, counter), errback=handle_error)
            event.wait()
            self.assertEquals(counter.next(), 100)
