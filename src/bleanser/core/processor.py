from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from pathlib import Path
import re
from subprocess import DEVNULL
from tempfile import TemporaryDirectory, gettempdir
from typing import Dict, Any, Iterator, Sequence, Optional, Tuple, Optional, Union, Callable, ContextManager, Protocol


from .common import CmpResult, Diff, Relation, logger, relations_to_instructions
from .utils import DummyExecutor


import more_itertools
from plumbum import local # type: ignore


GREP_FILTER = '> '


Input = Path
Cleaned = Path

class Cleaner(Protocol):
    def __call__(self, path: Input, *, wdir: Path) -> ContextManager[Cleaned]:
        pass


def relations(
        paths: Sequence[Path],
        *,
        cleanup: Cleaner,
        max_workers: Optional[int]=None,
        grep_filter: str,
        _wdir: Optional[Path]=None,
) -> Iterator[Relation]:
    # if wdir is passed will use this dir instead of a temporary
    # messy but makes debugging a bit easier..
    pool = DummyExecutor() if max_workers == 0 else ThreadPoolExecutor(max_workers=max_workers)
    with pool:
        workers = getattr(pool, '_max_workers')
        morkers = min(workers, len(paths))  # no point in using too many workers
        logger.info('using %d workers', workers)

        chunks = []
        futures = []
        for paths_chunk in more_itertools.divide(workers, paths):
            pp = list(paths_chunk)
            if len(pp) == 0:
                continue
            chunks.append(pp)
            futures.append(pool.submit(
                # force iterator, otherwise it'll still be basically serial
                lambda *args, **kwargs: list(_relations_serial(*args, **kwargs)),
                paths=pp,
                cleanup=cleanup,
                grep_filter=grep_filter,
                _wdir=_wdir,
            ))
        emitted = 0
        last: Optional[Path] = None
        for chunk, f in zip(chunks, futures):
            if last is not None:
                # yield fake relation just to fill the gap between chunks...
                # TODO kinda annying since it won't be idempotent...
                emitted += 1
                yield Relation(before=last, after=chunk[0], diff=Diff(cmp=CmpResult.DIFFERENT, diff=b''))
            last = chunk[0]
            rit = f.result()
            for r in rit:
                emitted += 1
                yield r
                last = r.after
        assert emitted == len(paths) - 1, (paths, emitted)


diff = local['diff']
grep = local['grep']
cmp_cmd = local['cmp']


# todo these are already normalized paths?
# although then harder to handle exceptions... ugh
def _relations_serial(
        paths: Sequence[Path],
        *,
        cleanup: Cleaner,
        grep_filter: str,
        _wdir: Optional[Path],
) -> Iterator[Relation]:
    assert len(paths) > 0
    # fast track.. so we don't compute dumps
    if len(paths) == 1:
        return []

    XX = Tuple[Input, Union[Exception, Cleaned]]
    XXX = Tuple[XX, XX]

    def outputs() -> Iterator[XXX]:
        with ExitStack() as stack:
            wdir: Path
            if _wdir is None:
                wdir = Path(stack.enter_context(TemporaryDirectory()))
            else:
                wdir = _wdir

            last: Optional[XX] = None
            for cp in paths:
                res: Union[Exception, Cleaned]
                try:
                    res = stack.enter_context(cleanup(cp, wdir=wdir))
                except Exception as e:
                    logger.exception(e)
                    res = e
                next_ = (cp, res)

                if last is not None:
                    yield (last, next_)
                    last_res = last[1]
                    if not isinstance(last_res, Exception):
                        # meh. a bit manual, but bounds the filesystem use by two dumps
                        last_res.unlink()  # todo no need to unlink in debug mode

                last = next_

    # TODO later, migrate core to use it?
    # diffing/relation generation can be generic

    for [(p1, dump1), (p2, dump2)] in outputs():
        logger.info("cleanup: %s vs %s", p1, p2)
        # todo would be nice to dump relation result?
        # TODO could also use sort + comm? not sure...
        # sorting might be a good idea actually... would work better with triples?

        def rel(*, before: Path, after: Path, diff: Diff) -> Relation:
            logger.debug('%s vs %s: %s', before, after, diff.cmp)
            return Relation(before=before, after=after, diff=diff)

        if isinstance(dump1, Exception) or isinstance(dump2, Exception):
            yield rel(before=p1, after=p2, diff=Diff(diff=b'', cmp=CmpResult.ERROR))
            continue

        # just for mypy...
        assert isinstance(dump1, Path), dump1
        assert isinstance(dump2, Path), dump2

        # first check if they are identical (should be super fast, stops at first byte difference)
        (rc, _, _) = cmp_cmd['--silent', dump1, dump2].run(retcode=(0, 1))
        if rc == 0:
            yield rel(before=p1, after=p2, diff=Diff(diff=b'', cmp=CmpResult.SAME))
            continue

        # print(diff[dump1, dump2](retcode=(0, 1)))  # for debug
        cmd = diff[dump1, dump2]  | grep['-vE', grep_filter]
        res = cmd(retcode=(0, 1))
        if len(res) > 10000:  # fast track to fail
            # TODO Meh
            yield rel(before=p1, after=p2, diff=Diff(diff=b'', cmp=CmpResult.DIFFERENT))
            continue
        rem = res.splitlines()
        # clean up diff crap like
        # 756587a756588,762590
        rem = [l for l in rem if not re.fullmatch(r'\d+a\d+(,\d+)?', l)]
        if len(rem) == 0:
            yield rel(before=p1, after=p2, diff=Diff(diff=b'', cmp=CmpResult.DOMINATES))
        else:
            # TODO maybe log verbose differences to a file?
            yield rel(before=p1, after=p2, diff=Diff(diff=b'', cmp=CmpResult.DIFFERENT))


# note: also some tests in sqlite.py

# TODO move to processor
def test_bounded_resources(tmp_path: Path) -> None:
    """
    Check that relation processing is iterative in terms of not using too much disk space for temporary files
    """

    one_mb = 1_000_000
    text = 'x' * one_mb + '\n'


    idir = tmp_path / 'idir'
    wdir = tmp_path / 'wdir'
    idir.mkdir()
    wdir.mkdir()

    # each file would be approx 1mb in size
    inputs = []
    for i in range(10):
        ip = idir / f'{i}.txt'
        text += '\n' + str(i) + '\n'
        ip.write_text(text)
        inputs.append(ip)
    ##

    # 'no-op' cleaner..
    @contextmanager
    def ident(path: Path, *, wdir: Path) -> Iterator[Path]:
        yield path

    func = lambda paths: relations(paths, cleanup=ident, max_workers=1, grep_filter=GREP_FILTER, _wdir=wdir)

    from .utils import total_dir_size

    for r in func(inputs):
        ds = total_dir_size(wdir)
        # at no point should use more than 2 dumps... + some leeway
        assert ds < 3 * one_mb, ds
        assert r.diff.cmp == CmpResult.DOMINATES