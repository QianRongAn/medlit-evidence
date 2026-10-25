"""Unbounded result traversal uses finite network batches and query-bound cursors."""
import re
import unittest
from unittest.mock import AsyncMock,patch
from app.pubmed import esearch_page,_page_token


class PubmedPagingTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_results_continue_beyond_the_initial_batch(self):
        ids,total,cursor=await esearch_page('query',2,first_result=(['1','2'],5))
        self.assertEqual(ids,['1','2']);self.assertIsNotNone(cursor)
        with patch('app.pubmed.esearch',AsyncMock(return_value=(['3','4'],5))) as search:
            ids,total,cursor=await esearch_page('query',2,cursor)
        self.assertEqual(search.call_args.kwargs['retstart'],2)
        with patch('app.pubmed.esearch',AsyncMock(return_value=(['5'],5))):
            ids,total,cursor=await esearch_page('query',2,cursor)
        self.assertEqual(ids,['5']);self.assertIsNone(cursor)

    async def test_cursor_is_query_bound_and_malformed_cursors_fail_before_network(self):
        token=_page_token('original',[[0,0,20]],100)
        with patch('app.pubmed.esearch',AsyncMock()) as search:
            for bad in (token,'not-json','!!!'):
                with self.assertRaises(ValueError):await esearch_page('different',100,bad)
            search.assert_not_awaited()

    async def test_uid_partition_traversal_exceeds_ten_thousand_without_duplicate_boundaries(self):
        requests=[]
        async def search(term,limit,retstart=0):
            match=re.search(r'(\d+):(\d+)\[UID\]',term)
            low,high=map(int,match.groups())
            values=range(max(1,low),min(10001,high)+1)
            size=len(values);requests.append((low,high,retstart))
            # Return synthetic IDs only for the current network page.
            return [str(x) for x in values[retstart:retstart+limit]],size
        all_ids=[]
        with patch('app.pubmed.esearch',AsyncMock(side_effect=search)):
            ids,total,cursor=await esearch_page('query',1000,first_result=([],10001))
            all_ids.extend(ids)
            while cursor:
                ids,total,cursor=await esearch_page('query',1000,cursor)
                all_ids.extend(ids)
        self.assertEqual(total,10001)
        self.assertEqual(len(all_ids),10001)
        self.assertEqual(set(all_ids),{str(i) for i in range(1,10002)})
        self.assertLess(len(requests),50)

    async def test_empty_page_before_end_is_an_error_not_a_fake_end(self):
        cursor=_page_token('query',[[0,0,2]],5)
        with patch('app.pubmed.esearch',AsyncMock(return_value=([],5))):
            with self.assertRaises(RuntimeError):await esearch_page('query',2,cursor)

class ContinuationFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_continuation_failure_never_appends_offline_demo(self):
        from app import main
        from fastapi import HTTPException
        with patch.object(main,'esearch_page',AsyncMock(side_effect=RuntimeError('network'))), patch.object(main,'load_corpus') as corpus:
            with self.assertRaises(HTTPException) as error:await main._retrieve('metformin',100,'cursor')
            self.assertEqual(error.exception.status_code,502)
            corpus.assert_not_called()

    async def test_invalid_cursor_returns_a_client_error_without_fallback(self):
        from app import main
        from app.pubmed import InvalidCursor
        from fastapi import HTTPException
        with patch.object(main,'esearch_page',AsyncMock(side_effect=InvalidCursor('bad cursor'))), patch.object(main,'load_corpus') as corpus:
            with self.assertRaises(HTTPException) as error:await main._retrieve('metformin',100,'cursor')
            self.assertEqual(error.exception.status_code,400)
            corpus.assert_not_called()
