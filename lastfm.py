#!/usr/bin/env python3
from argparse import ArgumentParser
import logging
from pathlib import Path
from subprocess import check_output, check_call, PIPE, run
from typing import Optional, List, Iterator, Iterable, Tuple, Optional
from tempfile import TemporaryDirectory
# make sure doesn't conain '<'

from kython import numbers
from kython.klogging import setup_logzero

# TODO ok, it should only start with '>' I guess?

Filter = str

def jq(path: Path, filt: Filter, output: Path):
    with output.open('wb') as fo:
        check_call(['jq', filt, str(path)], stdout=fo)

Result = List[Path]

from enum import Enum, auto

class CmpResult(Enum):
    DIFFERENT = 'different'
    SAME = 'same'
    DOMINATES = 'dominates'
R = CmpResult

from typing import NamedTuple


class Diff(NamedTuple):
    cmp: CmpResult
    diff: bytes


class XX(NamedTuple):
    path: Path
    diff_next: Optional[Diff]


class Relation(NamedTuple):
    before: Path
    diff: Diff
    after: Path



class Normaliser:
    def __init__(
            self,
            logger_tag='normaliser',
            delete_dominated=False,
            keep_both=True,
    ) -> None:
        self.logger = logging.getLogger()
        self.delete_dominated = delete_dominated
        self.keep_both = keep_both

    def main(self):
        setup_logzero(self.logger, level=logging.DEBUG)

    def extract(self) -> Filter:
        raise NotImplementedError

    def cleanup(self) -> Filter:
        raise NotImplementedError

    def _compare(self, before: Path, after: Path, tdir: Path) -> Diff:
        cmd = self.extract()
        norm_before = tdir.joinpath('before')
        norm_after = tdir.joinpath('after')

        jq(path=before, filt=cmd, output=norm_before)
        jq(path=after, filt=cmd, output=norm_after)

        # TODO hot to make it interactive? just output the command to compute diff?
        # TODO keep tmp dir??
        dres = run([
            'diff', str(norm_before), str(norm_after)
        ], stdout=PIPE)
        assert dres.returncode <= 1

        diff = dres.stdout
        diff_lines = diff.decode('utf8').splitlines()
        removed: List[str] = []
        for l in diff_lines:
            if l.startswith('<'):
                removed.append(l)

        if len(removed) == 0:
            if dres.returncode == 0:
                return Diff(CmpResult.SAME, diff)
            else:
                return Diff(CmpResult.DOMINATES, diff)
        else:
            return Diff(CmpResult.DIFFERENT, diff)

    def compare(self, *args, **kwargs) -> Diff:
        with TemporaryDirectory() as tdir:
            return self._compare(*args, **kwargs, tdir=Path(tdir)) # type: ignore

    def _iter_groups(self, relations: Iterable[Relation]):
        from typing import Any
        group: List[XX] = []

        def dump_group():
            if len(group) == 0:
                return []
            res = [g for g in group]
            group.clear()
            return [res]

        def group_add(path, diff):
            group.append(XX(path=path, diff_next=diff))

        last = None
        for i, rel in zip(numbers(), relations):
            if i != 0:
                assert last == rel.before
            last = rel.after

            res = rel.diff.cmp

            if res == CmpResult.DOMINATES:
                res = CmpResult.SAME if self.delete_dominated else CmpResult.DIFFERENT

            if res == CmpResult.DIFFERENT:
                group_add(rel.before, None)
                yield from dump_group()
            else:
                assert res == CmpResult.SAME
                group_add(rel.before, rel.diff)
        group_add(last, None)
        yield from dump_group()

    def _iter_deleted(self, relations: Iterable[Relation]) -> Iterator[XX]:
        groups = self._iter_groups(relations)
        for g in groups:
            if len(g) <= 1:
                continue
            delete_start = 1 if self.keep_both else 0
            yield from g[delete_start: -1]

    def _iter_relations(self, files) -> Iterator[Relation]:
        for i, before, after in zip(range(len(files)), files, files[1:]):
            self.logger.info('comparing %d: %s   %s', i, before, after)
            res, diff = self.compare(before, after)
            self.logger.info('result: %s', res)
            yield Relation(
                before=before,
                cmp=res,
                after=after,
                diff=diff,
            )

    def do(self, files, dry_run=True) -> None:
        def rm(pp: Path):
            if dry_run:
                self.logger.warning('dry run! would remove %s', pp)
            else:
                # TODO touch a bleanser file??
                raise RuntimeError

        relations = self._iter_relations(files=files)
        for d in self._iter_deleted(relations):
            rm(d)


def asrel(files, results) -> Iterator[Relation]:
    assert len(files) == len(results) + 1
    for b, res, a in zip(files, results, files[1:]):
        yield Relation(before=b, diff=Diff(res, b''), after=a)

def test0():
    P = Path
    nn = Normaliser(
        delete_dominated=True,
    )
    assert [[x.path for x in n] for n in nn._iter_groups(asrel(
        files=[
            P('a'),
            P('b'),
        ],
        results=[
            R.SAME,
        ],
    ))] == [
        [P('a'), P('b')],
    ]


def test1():
    P = Path
    # TODO kython this? it's quite common..
    nn = Normaliser(
        delete_dominated=True,
    )
    assert [[x.path for x in n] for n in nn._iter_groups(asrel(
        files=[
            P('a'),
            P('b'),
            P('c'),
            P('d'),
            P('e'),
            P('f'),
            P('g'),
            P('h'),
        ],
        results=[
            R.SAME, # ab
            R.DOMINATES, # bc
            R.DIFFERENT, # cd
            R.SAME, # de
            R.DIFFERENT, # ef
            R.SAME, # fg
            R.SAME, # gh
        ]
    ))]  == [
        [P('a'), P('b'), P('c')],
        [P('d'), P('e')],
        [P('f'), P('g'), P('h')],
    ]

def test2():
    P = Path
    files = [
        P('a'),
        P('b'),
        P('c'),
        P('d'),
        P('e'),
        P('f'),
        P('g'),
        P('h'),
    ]
    results = [
        R.DIFFERENT,
        R.DOMINATES,
        R.SAME,
        R.SAME,
        R.SAME,
        R.DIFFERENT,
        R.DOMINATES,
    ]
    nn = Normaliser(
        delete_dominated=False,
        keep_both=True,
    )
    assert [x.path for x in nn._iter_deleted(asrel(
        files=files,
        results=results,
    ))] == [P('d'), P('e')]

    nn2 = Normaliser(
        delete_dominated=True,
        keep_both=False,
    )
    assert [x.path for x in nn2._iter_deleted(asrel(
        files=files,
        results=results,
    ))] == [P('b'), P('c'), P('d'), P('e'), P('g')]



ID_FILTER = '.'

class LastfmNormaliser(Normaliser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, logger_tag='lastfm-normaliser', delete_dominated=True, keep_both=False)

    def extract(self) -> Filter:
        return 'sort_by(.date) | map(map_values(ascii_downcase))'

    def cleanup(self) -> Filter:
        return ID_FILTER


# TODO FIXME make sure to store .bleanser file with diff? or don't bother?


def main():
    bdir = Path('lastfm')

    norm = LastfmNormaliser()
    norm.main()
    p = ArgumentParser()
    p.add_argument('--dry', action='store_true')
    p.add_argument('before', nargs='?')
    p.add_argument('after', nargs='?')
    p.add_argument('--all', action='store_true')
    args = p.parse_args()
    if args.all:
        backups = list(sorted(bdir.glob('*.json')))
    else:
        assert args.before is not None
        assert args.after is not None
        backups = [args.before, args.after]

    norm.do(backups, dry_run=args.dry)

if __name__ == '__main__':
    main()
