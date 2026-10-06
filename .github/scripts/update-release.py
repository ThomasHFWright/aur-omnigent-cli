#!/usr/bin/env python3
"""Resolve supported versions; put every download and hash in makepkg's sources."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename

FIRST_PARTY = ('omnigent', 'omnigent-client', 'omnigent-ui-sdk')
LOCAL = ('requirements.txt', 'omnigent', 'smoke-test.py', 'LicenseRef-bundled-dependencies')


def fetch_json(url):
    with urlopen(Request(url, headers={'User-Agent': 'aur-omnigent-cli'}), timeout=60) as response:
        return json.load(response)


def stable_version(release):
    tag = release['tag_name']
    if release['draft'] or release['prerelease'] or not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Expected a published stable vX.Y.Z release')
    return tag[1:]


def artifact(url, digest):
    parsed = urlsplit(url)
    filename = parsed.path.rsplit('/', 1)[-1]
    if parsed.scheme != 'https' or parsed.netloc != 'files.pythonhosted.org':
        raise ValueError(f'Unexpected artifact origin: {url}')
    if not re.fullmatch(r'[A-Za-z0-9_.+-]+', filename) or not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('Invalid artifact filename or SHA-256')
    return f'{filename}::{url}', digest


def main():
    if sys.argv[1:] == ['--self-test']:
        assert stable_version(dict(tag_name='v0.17.0', draft=False, prerelease=False)) == '0.17.0'
        for tag in ['main', 'v0.17.0rc1', 'v1.2.3;echo bad']:
            try:
                stable_version(dict(tag_name=tag, draft=False, prerelease=False))
            except ValueError:
                pass
            else:
                raise AssertionError(tag)
        try:
            artifact('https://untrusted.example/package.whl', 'a' * 64)
        except ValueError:
            pass
        else:
            raise AssertionError('Accepted an unexpected artifact origin')
        print('PASS release and artifact validation')
        return

    if sys.platform != 'linux' or __import__('platform').machine() != 'x86_64':
        raise SystemExit('Generate the recipe on x86_64 Linux with system Python')
    version = stable_version(fetch_json('https://api.github.com/repos/omnigent-ai/omnigent/releases/latest'))
    recipe_path = Path('PKGBUILD')
    recipe = recipe_path.read_text()
    current = re.search(r'^pkgver=(.+)$', recipe, re.M)[1]
    if int(subprocess.check_output(['vercmp', version, current])) < 0:
        raise SystemExit('Refusing to downgrade the stable recipe')
    python = f'{sys.version_info.major}.{sys.version_info.minor}'
    next_python = f'{sys.version_info.major}.{sys.version_info.minor + 1}'
    tomorrow = str(datetime.datetime.now(datetime.UTC).date() + datetime.timedelta(days=1))
    with tempfile.TemporaryDirectory(prefix='omnigent-lock-') as directory:
        root = Path(directory)
        (root / 'requirements.in').write_text(f'omnigent=={version}\n')
        command = ['uv', 'pip', 'compile', str(root / 'requirements.in'), '--upgrade',
                   '--python-version', python, '--python-platform', 'x86_64-unknown-linux-gnu',
                   '--only-binary', ':all:', '--exclude-newer', '7d', '--format', 'pylock.toml',
                   '-o', str(root / 'pylock.toml'), '--quiet']
        for name in FIRST_PARTY:
            command += ['--exclude-newer-package', f'{name}={tomorrow}']
        subprocess.run(command, check=True)
        lock = tomllib.loads((root / 'pylock.toml').read_text())

    artifacts = []
    for name in FIRST_PARTY:
        release = fetch_json(f'https://pypi.org/pypi/{name}/{version}/json')
        source = next(item for item in release['urls'] if item['packagetype'] == 'sdist')
        artifacts.append(artifact(source['url'], source['digests']['sha256']))
    ranks = {tag: rank for rank, tag in enumerate(sys_tags())}
    requirements = []
    for package in lock['packages']:
        if package['name'] in FIRST_PARTY:
            continue
        candidates = []
        for wheel in package['wheels']:
            filename = urlsplit(wheel['url']).path.rsplit('/', 1)[-1]
            compatible = [ranks[tag] for tag in parse_wheel_filename(filename)[3] if tag in ranks]
            if compatible:
                candidates.append((min(compatible), wheel['url'], wheel['hashes']['sha256']))
        if not candidates:
            raise ValueError(f'No compatible wheel for {package["name"]}')
        _, url, digest = min(candidates)
        artifacts.append(artifact(url, digest))
        requirements.append(f'{package["name"]}=={package["version"]} --hash=sha256:{digest}\n')
    Path('requirements.txt').write_text(''.join(requirements))
    backend = fetch_json('https://pypi.org/pypi/hatchling/1.31.0/json')
    wheel = next(item for item in backend['urls'] if item['packagetype'] == 'bdist_wheel')
    artifacts.append(artifact(wheel['url'], wheel['digests']['sha256']))
    artifacts.extend((name, hashlib.sha256(Path(name).read_bytes()).hexdigest()) for name in LOCAL)
    block = '# BEGIN GENERATED SOURCES\n'
    block += 'source=(' + '\n        '.join(shlex.quote(url) for url, _ in artifacts) + ')\n'
    block += 'sha256sums=(' + '\n            '.join(shlex.quote(digest) for _, digest in artifacts) + ')\n'
    block += 'noextract=(' + '\n           '.join(shlex.quote(url.split('::')[0]) for url, _ in artifacts if '.whl::' in url) + ')\n'
    block += '# END GENERATED SOURCES'
    updated, count = re.subn(r'# BEGIN GENERATED SOURCES.*?# END GENERATED SOURCES', lambda _: block, recipe, flags=re.S)
    assert count == 1
    updated = re.sub(r'^pkgver=.+$', f'pkgver={version}', updated, flags=re.M)
    updated = re.sub(r'^_python=.+$', f'_python={python}', updated, flags=re.M)
    updated = re.sub(r"'python>=[0-9.]+\' 'python<[0-9.]+'", f"'python>={python}' 'python<{next_python}'", updated)
    if updated != recipe:
        release = 1 if version != current or 'source=()' in recipe else int(re.search(r'^pkgrel=(\d+)$', recipe, re.M)[1]) + 1
        updated = re.sub(r'^pkgrel=\d+$', f'pkgrel={release}', updated, flags=re.M)
        recipe_path.write_text(updated)
    Path('.SRCINFO').write_bytes(subprocess.check_output(['makepkg', '--printsrcinfo']))
    print(f'Prepared {version} for Python {python}; {len(requirements)} runtime dependencies. Publication requires a successful build.')


if __name__ == '__main__':
    main()
