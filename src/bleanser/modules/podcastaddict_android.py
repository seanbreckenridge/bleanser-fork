#!/usr/bin/env python3
from bleanser.core.sqlite import SqliteNormaliser, Tool
from bleanser.core.utils import get_tables


class Normaliser(SqliteNormaliser):
    MULTIWAY = True
    DELETE_DOMINATED = True

    def check(self, c) -> None:
        tables = Tool(c).get_schemas()
        assert 'podcasts' in tables, tables
        eps = tables['episodes']
        # to make sure it's safe to use multiway/delete dominated:
        assert 'playbackDate' in eps
        assert 'position_to_resume' in eps

    # TODO I guess the point is that they run before even trying to cleanup the database, as sanity checks
    # guess makes more sense to implement base 'check' mehod

    # def __init__(self, db: Path) -> None:
    #     with self.checked(db) as conn:
    #         self.tables = get_tables(conn)
    #

    def cleanup(self, c) -> None:
        self.check(c)

        t = Tool(c)
        ## often changing, no point keeping
        t.drop_cols(table='episodes', cols=[
            'thumbnail_id',
            'new_status',

            'downloaded_status_int',
        ])
        t.drop_cols(table='podcasts', cols=[
            'last_modified',
            'etag',  # ?? sometimes contains quoted last_modified or something..
            'rating',
            'reviews',
            'iTunesID',
            'latest_publication_date',
            'averageDuration',
            'frequency',
            'episodesNb',
            'subscribers',
            'thumbnail_id',
            'update_date', 'update_status',
            'filter_chapter_excluded_keywords',

            'category',
            'explicit',
            'server_id',
        ])
        ##

        ## changing often and likely not interesting
        t.drop('ad_campaign')
        t.drop('bitmaps')
        t.drop('blocking_services')
        t.drop('fts_virtual_episode_docsize')
        t.drop('fts_virtual_episode_segments')
        t.drop('fts_virtual_episode_segdir')
        t.drop('ordered_list')  # just some random numbers, always changing
        t.drop('statistics') # just some random numbers, mostly empty
        t.drop('radio_search_results')
        t.drop('topics')  # some random topic names.. at some point just disappeared
        return

        ## probably unnecessary?
        tool.drop('chapters')
        tool.drop('teams')
        tool.drop('topics')
        tool.drop('relatedPodcasts')
        tool.drop('content_policy_violation')  # lol
        ##


if __name__ == '__main__':
    Normaliser.main()


def test_podcastaddict() -> None:
    from bleanser.tests.common import TESTDATA, actions2
    res = actions2(path=TESTDATA / 'podcastaddict_android', rglob='*.db*', Normaliser=Normaliser)
    assert res.remaining == [
        '20180106220736/podcastAddict.db',
        '20190227212300/podcastAddict.db',
        '20200217195816/podcastAddict.db',

        '20200406041500/podcastAddict.db',
        # '20210306070017/podcastAddict.db',
        # '20210306070020/podcastAddict.db',
        '20210306140046/podcastAddict.db',

        # keep: episode position changed
        '20210306165958/podcastAddict.db',

        '20210509141916/podcastAddict.db',
        # '20210510070001/podcastAddict.db',
        # '20210511185801/podcastAddict.db',
        # '20210513164819/podcastAddict.db',
        # some podcast lengths changed... might be useful
        '20210517000609/podcastAddict.db',
        # '20211226145720/podcastAddict.db',
        '20211226172310/podcastAddict.db',
        # some podcast authors changed... dunno if useful but whatever
        '20211228010151/podcastAddict.db',
    ]
