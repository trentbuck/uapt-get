import datetime
import logging
import os
import pathlib
import urllib.request
import argparse
import gzip
import tempfile
import subprocess


__doc__ = """user mode apt

• allow unprivileged user to install and run software.
• don't require apt, dpkg, &c (i.e. use ONLY cpython3).
  (FIXME: currently also needs external ar, GNU tar, gzip, xz, zstd)

Personally I think this is a faster & better answer:

    mmdebstrap stable /dev/null --include=X,Y,Z \
               --customize-hook='chroot $1 bash; false'

But obviously that doesn't have the ability to read/write your regular files.
Maybe that's a good thing, though? ;-)
"""

root_path = pathlib.Path().home() / '.local/share/uapt'
mirror = 'https://deb.debian.org/debian'
release = 'stable'
# FIXME: rv64gc and arm64
architecture = {'x86_64': 'amd64'}[os.uname().machine]
packages_path = root_path / 'Packages.gz'


def update():
    root_path.mkdir(mode=0o0700, parents=True, exist_ok=True)
    rfc5322_fmt = '%a, %d %b %Y %H:%M:%S GMT'
    request = urllib.request.Request(
        url=f'{mirror}/dists/{release}/main/binary-{architecture}/Packages.gz')
    try:
        request.headers['if-modified-since'] = datetime.datetime.fromtimestamp(
            packages_path.stat().st_mtime).strftime(rfc5322_fmt)
    except FileNotFoundError:
        logging.debug('No Packages.gz yet - no worries')
    try:
        with urllib.request.urlopen(request) as resp:
            packages_path.write_bytes(resp.read())
            timestamp = datetime.datetime.strptime(
                resp.headers['last-modified'],
                rfc5322_fmt).replace(
                    tzinfo=datetime.timezone.utc).timestamp()
            os.utime(packages_path, times=(timestamp, timestamp))
    except urllib.error.HTTPError as e:
        if e.code == 304:       # Not Modified
            logging.info('Packages already up-to-date')
        else:
            raise


def install(*packages):
    update()
    for package in packages:
        install1(package)


def install1(package_name):
    with gzip.open(packages_path, mode='rt') as f:
        for line in f:
            if line == f'Package: {package_name}\n':
                for line in f:
                    if line.startswith('Filename: '):
                        filename = line.split()[-1]
                        uri = f'{mirror}/{filename}'
                        break
                    if line == '\n':
                        raise RuntimeError('Package found, but no URL?')
                break
        else:
            raise RuntimeError('No such package', package_name)
    logging.debug('Found URI to download: %s', uri)
    # FIXME: does python have a built-in ar implementation???
    #        If so we can avoid tempfile & subprocess.
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        deb_path = td / 'tmp.deb'
        with urllib.request.urlopen(uri) as resp:
            deb_path.write_bytes(resp.read())
        data_filename, = (
            line.strip()
            for line in subprocess.check_output(
                    ['busybox', 'ar', '-t', deb_path],
                    text=True).splitlines()
            if line.startswith('data.tar.'))
        subprocess.check_call(
            ['busybox', 'ar', '-x', deb_path, data_filename],
            cwd=td)
        data_path = td / data_filename
        # FIXME: can't use python tarfile, because
        #        it might be 'data.tar.gz' (easy) but
        #        it might be 'data.tar.zst' (…fuck).
        # FIXME: can't use "busybox tar" or BSD tar either.
        subprocess.check_call(['tar', 'xf', data_path], cwd=root_path)


# This is meant to be simple like "opkg list", not fancy like apt/apt-cache.
def list():
    update()
    with gzip.open(packages_path, mode='rt') as f:
        for line in f:
            if line.startswith('Package: '):
                print(line.split()[-1], end='\t')
            if line.startswith('Description: '):
                print(line.strip().partition(' ')[2])


def run(*args):
    os.environ['PATH'] = ':'.join([
        str(root_path / 'usr/sbin'),
        str(root_path / 'sbin'),
        str(root_path / 'usr/bin'),
        str(root_path / 'bin'),
        str(root_path / 'usr/games'),
        os.environ['PATH']])
    os.environ['LD_LIBRARY_PATH'] = str(root_path / 'usr/lib')
    subprocess.check_call(args)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)
    p1 = subparsers.add_parser('update')
    p1.set_defaults(function=update, args=[])
    p2 = subparsers.add_parser('list')
    p2.set_defaults(function=list, args=[])
    p3 = subparsers.add_parser('install')
    p3.set_defaults(function=install)
    p3.add_argument('args', nargs='+')
    p4 = subparsers.add_parser('run')
    p4.set_defaults(function=run)
    p4.add_argument('args', nargs='+')
    args = parser.parse_args()
    args.function(*args.args)
