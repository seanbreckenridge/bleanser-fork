#!/usr/bin/env python3
from bleanser.core.modules.json import JsonNormaliser, Json, delkeys


class Normaliser(JsonNormaliser):
    MULTIWAY = True
    PRUNE_DOMINATED = True

    def cleanup(self, j: Json) -> Json:
        delkeys(j, keys={
            'popularity',  # flaky -- relative to other artists, not interesting
            'album_type',  # sometimes flaky between 'album' and 'compilation'

            ## flaky metadata (maybe not even worth backing up..)
            'available_markets',
            'images',
            'total_episodes',
            'preview_url',
            'release_date',
            'external_ids',
            ##

            # present on playlists, basically hash
            'snapshot_id',

        })

        if isinstance(j, list):
            # old format, I think this was just 'Liked' playlist
            return j

        ## 'flatten' to make it possible to properly diff
        playlists = j['playlists']
        upd_playlists = []
        for p in playlists:
            pname = p['name']
            if p['owner']['id'] == 'spotify':
                # these are typically autogenerated playlists like
                # - "This Is " artist playlists
                # - mix between two users
                # they change very often and no point keeping track of them
                continue
            pid = p['id']
            j[f'playlist_{pid}_tracks'] = p['tracks']
            upd_playlists.append(p)
            del p['tracks']
        j['playlists'] = upd_playlists
        ##

        # TODO ugh. tbh, not sure what to do with recently_played -- api only allows recent 50?
        # so they are bound to change super often if you listen to music daily (+ you might even miss some tracks anyway)

        return j


if __name__ == '__main__':
    Normaliser.main()
