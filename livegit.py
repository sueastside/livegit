import os, sys
import glob
import fnmatch
import shutil
import subprocess
import functools
import argparse
import socket
from threading import Thread
import asyncio
from pathlib import Path
from time import sleep, time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from watchfiles import awatch, Change, DefaultFilter

import tempfile
from typing import Callable
import errno
import stat

def handle_remove_readonly(func: Callable, path: str, exc) -> None:
    """Handle errors when trying to remove read-only files through `shutil.rmtree`.
    This handler makes sure the given file is writable, then re-execute the given removal function.
    Arguments:
        func: An OS-dependant function used to remove a file.
        path: The path to the file to remove.
        exc: A `sys.exc_info()` object.
    """
    excvalue = exc[1]
    if func in (os.rmdir, os.remove, os.unlink) and excvalue.errno == errno.EACCES:
        os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # 0777
        func(path)
    else:
        raise

class TemporaryDirectory(tempfile.TemporaryDirectory):
    """A custom version of `tempfile.TemporaryDirectory` that handles read-only files better.
    On Windows, before Python 3.8, `shutil.rmtree` does not handle read-only files very well.
    This custom class makes use of a [special error handler][copier.tools.handle_remove_readonly]
    to make sure that a temporary directory containing read-only files (typically created
    when git-cloning a repository) is properly cleaned-up (i.e. removed) after using it
    in a context manager.
    """

    @classmethod
    def _cleanup(cls, name, warn_message):
        cls._robust_cleanup(name)
        warnings.warn(warn_message, ResourceWarning)

    def cleanup(self):
        if self._finalizer.detach():
            self._robust_cleanup(self.name)

    @staticmethod
    def _robust_cleanup(name):
        shutil.rmtree(name, ignore_errors=False, onerror=handle_remove_readonly)


class WebFilter(DefaultFilter):
    def __init__(self, ignore_files):
        self.ignore_files = ignore_files
        super().__init__()

    def __call__(self, change: Change, path: str) -> bool:
        return (
            super().__call__(change, path) and
            not any([fnmatch.filter(path, ignore) for ignore in self.ignore_files])
        )

async def watch_directory(stop_event, path_to_watch: Path, ignore_files, staging_directory: Path, bare_directory: Path):
    async for changes in awatch(path_to_watch, debug=False, step=500, watch_filter=WebFilter(ignore_files), stop_event=stop_event):
        for change in changes:
            type, file = change
            print('change', type, file)
            if not os.path.isfile(file):
                continue
            if type == Change.modified or type == Change.added:
                destination = (staging_directory / Path(file).relative_to(path_to_watch)).parent
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, destination)
            elif type == Change.deleted:
                p =  staging_directory / Path(file).relative_to(path_to_watch)
                if os.path.exists(p):
                    os.remove(p)
            #commit changes
            Popen(["git", "add", '-A'], cwd=staging_directory)
            Popen(["git", "commit", '-m', f'{str(type)} {Path(file).relative_to(path_to_watch)}'], cwd=staging_directory)
        #sync
        Popen(["git", "push", '--all', str(bare_directory)], cwd=staging_directory)


def test(path: Path):
    def sleep_write(path: Path):
        sleep(1.1)
        import uuid
        path.write_text('hello'+str(uuid.uuid4()))
    thread = Thread(target=sleep_write, args=(path,))
    thread.start()
    return thread


def Popen(*args, **kwargs):
    process = subprocess.Popen(*args, **kwargs)
    process.communicate()


def get_ignores(path_to_watch: Path):
    ignore_files = ['.git/']
    if os.path.isfile(path_to_watch / '.gitignore'):
        with open(path_to_watch / '.gitignore') as f:
            for line in f.readlines():
                ignore_files.append(line.strip())
    return ignore_files


def initialize(directory, ignore_files):
    #Create staging dir
    staging_directory = directory / Path("staging/")
    staging_directory.mkdir(parents=True, exist_ok=True)
    Popen(["git", "init"], cwd=staging_directory)

    # Copy current state
    print('ignores', ignore_files)
    for file in glob.iglob(str(path_to_watch)+'/**', recursive=True):
        if not any([fnmatch.filter(file, ignore) for ignore in ignore_files]) and os.path.isfile(path_to_watch / file):
            destination = (staging_directory / Path(file).relative_to(path_to_watch)).parent
            print(f'Copying {file} to {destination}')
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)
            #break
    Popen(["git", "add", '-A'], cwd=staging_directory)
    Popen(["git", "commit", '-m', 'init'], cwd=staging_directory)


    #Create serving repo
    bare_directory = directory / Path("bare/")
    #bare_directory.mkdir(parents=True, exist_ok=True)
    Popen(["git", "clone", '--bare', str(staging_directory), str(bare_directory)], cwd=directory)
    Popen(["git", '--bare', 'update-server-info'], cwd=bare_directory)

    p = Path(bare_directory, 'hooks', 'post-update.sample')
    p.rename(Path(p.parent, "post-update"))

    Popen(["git", "push", '--all', str(bare_directory)], cwd=staging_directory)

    return staging_directory, bare_directory


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', help='The path to watch', default='.')
    parser.add_argument('--port', help='The port to run the server on', type=int, default=8000)
    args = parser.parse_args()
   
    path_to_watch = Path(args.path).resolve()
    with TemporaryDirectory(prefix='livegit__') as directory:
        print('current directory', path_to_watch)
        print('created temporary directory', directory)

        ignore_files = get_ignores(path_to_watch)

        staging_directory, bare_directory = initialize(directory, ignore_files)

        hostname = socket. gethostname()
        local_ip = socket. gethostbyname(hostname)
        print('-'*40)
        print(f'Server listening on http://{local_ip}:{args.port} ...')
        print()
        print(f'You can now do "git clone http://{local_ip}:{args.port}"" ')
        print('-'*40)

        Handler = functools.partial(SimpleHTTPRequestHandler, directory=str(bare_directory))
        httpd = ThreadingHTTPServer(('', args.port), Handler)

        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()

        t = Thread(target=httpd.serve_forever)
        t.start()
        test(path_to_watch / 'foo.txt')

        def stop_loop():
            input('Press <enter> to stop')
            print('stopping')
            stop_event.set()
            httpd.shutdown()

        Thread(target=stop_loop).start()
        loop.run_until_complete(asyncio.gather(watch_directory(stop_event, path_to_watch, ignore_files, staging_directory, bare_directory)))



