import argparse
import html
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import md5

try:
    from functools import cache
except ImportError:
    from functools import lru_cache as cache

import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

# from typing import Literal


logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("alexandria")

SHELL_LINK_MASK = "\u001b]8;;{}\u001b\\{}\u001b]8;;\u001b\\"


class ExternalExecutableNotFound(Exception):
    pass


class StaticNotFound(Exception):
    pass


class URLInvalid(Exception):
    pass


def find_executable(cmds: list[str]) -> str | None:
    for cmd in cmds:
        if shutil.which(cmd):
            return cmd
    return None


def run_command(cmd: str, args: list[str], quiet: bool = False) -> subprocess.CompletedProcess:
    stderr = subprocess.DEVNULL if quiet else None
    stdout = subprocess.DEVNULL if quiet else None
    full_cmd = [cmd] + args
    logger.info(f"Running command: {full_cmd}")
    return subprocess.run(full_cmd, check=False, stderr=stderr, stdout=stdout)


def chrome_screenshot(url: URL, output_path: Path):
    cmd = find_executable(["chromium", "chrome"])
    if cmd is None:
        return None

    screenshot_dest = output_path / Path(url.unique() + '.png')
    args = [
            "--run-all-compositor-stages-before-draw",
            "--disable-gpu",
            "--headless=new",
            "--virtual-time-budget=30000",
            "--hide-scrollbars",
            "--window-size=1920,4000",
            f"--screenshot={screenshot_dest}",
            str(url),
    ]
    return run_command(cmd, args, quiet=True)


def wget_download_page(url: URL, output_path: Path, deep: int = 1, gzip: bool = False):
    cmd = find_executable(["wget"])
    if cmd is None:
        raise ExternalExecutableNotFound("wget is required dependency")

    args = [
        "--header", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "--header", "User-Agent: Mozilla/5.0 (compatible; Heritrix/3.0 +http://archive.org)",
        "--header", "Accept: text/html,application/xhtml+xml",
        "--header", "Accept-Language: pt-BR,pt;q=0.9,en;q=0.8",
        "--header", "DNT: 1",
        "--header", "Connection: keep-alive",
        "--header", "Upgrade-Insecure-Requests: 1",
        "--header", "Sec-Fetch-Dest: document",
        "--header", "Sec-Fetch-Mode: navigate",
        "--header", "Sec-Fetch-Site: none",
        "--header", "Sec-Fetch-User: ?1",
        "--header", "Cache-Control: max-age=0",
        "--mirror",
        "-p",
        "--recursive",
        "--page-requisites",
        "--adjust-extension",
        "--span-hosts",
        "-U", "'Mozilla'",
        "-E",
        "-k",
        "-e", "robots=off", "--random-wait", "--no-cookies",
        "--convert-links", "--restrict-file-names=windows",
        "-l", str(deep),
        "-P", str(output_path),
        "--no-parent", str(url),
        "--domains", url.netloc,
    ]
    if gzip:
        args.extend(["--header", "Accept-Encoding: gzip, deflate, br"])

    return run_command(cmd, args, quiet=False)

# class Git(ExternalDependency):
#     quiet = True
#     cmd = ["git"]
#     def __init__(self, path, init=True):
#         self.path = Path(path)
#         self.args = ["-C", str(self.path)]
#         if init and not self.is_git_repo:
#             self.run(["init"], True)
#     @property
#     def is_git_repo(self):
#         return (self.path / Path(".git")).is_dir()
#     def get_head(self):
#         return self.run(["symbolic-ref", "--short", "HEAD"], True)
#     def get_origin(self):
#         return self.run(["remote"], True)
#     def push(self):
#         pass
#     def commit(self, message):
#         return self.run(["commit", "-m", message], True)
#     def add(self, stages="."):
#         return self.run(["add", stages], True)

@dataclass(init=False)
class URL:
    scheme: str
    netloc: str
    path: str
    params: str
    query: str
    fragment: str

    original_url: str

    def __init__(self, url):
        url_p = urlparse(url)

        if not url_p.scheme and not url_p.netloc:
            raise URLInvalid(f"{url} is not valid URL")

        if url_p.scheme not in ["", "https", "http"]:
            raise URLInvalid(f"{url} is not HTTP or HTTPS")

        self.original_url = url
        self.scheme = url_p.scheme
        self.netloc = url_p.netloc
        self.path = url_p.path
        self.params = url_p.params
        self.query = url_p.query
        self.fragment = url_p.fragment

    def __eq__(self, other):
        return self.original_url == other.original_url

    def __hash__(self):
        return hash(self.original_url)

    def __str__(self):
        return self.original_url

    def unique(self):
        return md5(str(self.original_url).encode("utf-8")).hexdigest()


class HTMLParser:
    # this only parses basic tags, do not use as AST analizer
    # using HTMLParser from html.parser shows slower, maybe later.
    re_find_title = re.compile(
        r"<title.*?>(.+?)</title>", flags=re.IGNORECASE | re.DOTALL
    )

    def __init__(self, file_path: Path):
        self.file_path = file_path

    def title(self):
        # improve this to clamp the file size with some max_size (100MB+) instead arbitrary 50% file size
        read_bytes = int(self.file_path.stat().st_size * 0.5)  # 50% arbitrary number

        with open(self.file_path, "rb") as f:
            html_cont = f.read(read_bytes).decode(errors="replace")

        if re_match := self.re_find_title.search(html_cont):
            return html.unescape(re_match.groups()[0])
        return self.file_path.name


@dataclass(kw_only=True)
class Website:
    url: URL
    created_at: datetime = field(default_factory=datetime.now) ## TODO rename "at"

    # status: Literal["ON_DISK", "LINK_ONLY"] | None = None

    def __post_init__(self):
        self.url = URL(str(self.url))

        if not isinstance(self.created_at, datetime):
            self.created_at = datetime.fromisoformat(self.created_at)

    def __hash__(self):
        return hash(self.url)

    def __eq__(self, other):
        assert isinstance(other, type(self)), type(other)
        return other.url == self.url

    def json(self):
        return {"url": str(self.url), "created_at": self.created_at.isoformat()}


class StaticFiles:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.root.mkdir(exist_ok=True, parents=True)

    @cache
    def directory_size(self, path) -> int:
        total = 0
        for e in path.iterdir():
            if e.is_dir():
                total += self.directory_size(e)
            if e.is_file():
                total += e.stat().st_size
        return total

    def size(self):
        return self.directory_size(self.root)

class WebsiteStaticFiles(StaticFiles):
    def find_html_index(self, url: URL) -> Path:
        path = self.root / Path(f"{url.netloc}/{url.path}")
        possibles_files = [
            path,
            path / "index.html",
            str(path) + ".html",
            str(path) + ("index.html@" + url.query + ".html"),
            str(path) + ("@" + url.query + ".html"),
        ]
        for f in possibles_files:
            fp = Path(f)
            if fp.is_file():
                return fp

        err = "\n".join(str(p) for p in possibles_files)
        raise StaticNotFound(
            (
                "unreachable - cound not determinate the index HTML file!\n"
                f"url: {url}\n"
                f"path: {path}\n"
                "all the tested files:\n"
                f"{err}"
                "\nplease, fix me\n"
            )
        )

    def size_domain_url(self, url: URL) -> int:
        path = self.root / url.netloc
        if not path.exists():
            return 0
        return self.directory_size(path)


class ScreenshotsStaticFiles(StaticFiles):
    def find_screenshot(self, url: URL):
        return self.root / f"{url.unique()}.png"


class Humanizer:
    def clean_title(self, title):
        return title.replace("|", "-").replace("\n", "")

    def size(self, num):
        if num == 0:
            return "0 B"

        KiB = 1024
        units = ("KiB", "MiB", "GiB")
        for u in units:
            num /= KiB
            if abs(num) < KiB:
                break
        return f"{num:3.1f} {u}"

    def truncate_url(self, url: URL, max_trunc=45):
        url_str = (
            str(url)
            .removeprefix("https://")
            .removeprefix("http://")
            .removeprefix("www.")
        )
        if len(url_str) > max_trunc:
            url_str = url_str[:max_trunc] + "(...)"
        return url_str

    def datetime(self, dt):
        datetime_fmt = "%d. %B %Y %I:%M%p"
        return dt.strftime(datetime_fmt)


def main(args):
    if args.quiet:
        logger.setLevel(logging.INFO)
    logger.info("Alexandria - Internet preservation")

    humanizer = Humanizer()
    website_sf = WebsiteStaticFiles(args.files)
    screenshot_sf = ScreenshotsStaticFiles(args.screenshots)

    # Database
    if args.database.exists():
        with open(args.database, "r") as f:
            db = json.load(f)
    else:
        db = {}
    logger.info(f"Loaded file {args.database}")

    # Load Websites
    if "websites" not in db:
        db["websites"] = []

    websites = [
        Website(url = web["url"], created_at = web["created_at"])
        for web in db["websites"]
    ]
    websites.sort(key=lambda web: web.created_at, reverse=True)
    unique_domains = set(web.url.netloc for web in websites)
    logger.info(f"Total websites {len(websites)} - Total unique domains {len(unique_domains)}")

    # Generate README
    with open(args.readme, "w") as f:
        today = humanizer.datetime(datetime.now())
        itens_content = "\n".join(
            "| [{url}]({url}) | {time} |".format(url=web.url, time=humanizer.datetime(web.created_at))
            for web in websites
        )
        content = (
            f"# Alexandria - generated from database at {today}\n"
            "| URL  | Created at |\n"
            "| ---- | ---------- |\n"
            f"{itens_content}\n"
        )
        f.write(str(content))
        logger.info(f"README as generated at: {args.readme}.")


    # Generate HTML
    HTML_CONTENT = None
    with open(args.index, "w") as f:
        with open("template.html", "r", encoding='utf-8') as t:
            html_template = t.read()

        # <td><span><a href="{snapshot.screenshot}">&#x1F4F7;</a></span></td>
        table_line = """
        <tr>
         <td><a href="{url}">{url}</a></td>
         <td>{size}</td>
         <td>{created_at}</td>
        </tr>"""
        table = """
        <table>
         <tr>
           <th>URL</th>
           <th>Size</th>
           <th>Created at</th>
         </tr>
          {content}
         </table>
        """
        table_content = table.format(
            content = " ".join(table_line.format(
                url=web.url,
                size=humanizer.size(website_sf.size_domain_url(web.url)),
                created_at=humanizer.datetime(web.created_at)
            ) for web in websites)
        )
        content = html_template.format(
            table=table_content,
            total_unique_domains=len(unique_domains),
            total=len(websites),
            total_size=humanizer.size(
                website_sf.size() + screenshot_sf.size()
            ),
        )
        f.write(str(content))
        HTML_CONTENT = content
        logger.info(f"HTML as generated at: {args.index}.")

    # Download
    if args.urls:
        for url in args.urls:
            new_website = Website(url = url)
            if new_website in websites:
                 logger.warning(f"{url} is already in the database - skiping this download")
                 continue

            wget_download_page(new_website.url, args.files)
            chrome_screenshot(new_website.url, args.screenshots)
            if website_sf.find_html_index(new_website.url): # if index has found - it means success, remove to enable "link only" type
                db["websites"].append(new_website.json())

        with open(args.database, "w") as f:
            json.dump(db, f, indent=4)
        # catch keyboard exit

    # Server
    else:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(bytes(HTML_CONTENT, "utf-8"))

            def log_message(self, format, *args):
                logger.info(format % args)

            def log_error(self, format, *args):
                logger.error(format % args)

        logger.info("Server at: " + SHELL_LINK_MASK.format(f"http://localhost:{args.port}", f"localhost:{args.port}"))
        try:
            HTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
        except KeyboardInterrupt:
            pass

    logger.info("Bye!")


if __name__ == "__main__":
    argsparser = argparse.ArgumentParser(
        prog="./python alexandria.py",
        description="Alexandria - Tool to download and browser your own internet backup",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    argsparser.add_argument("urls", help="One or multiple URLs to preserve", nargs="*")

    argsparser.add_argument("-p", "--port", help="Server HTTP port", default=8000, type=int)
    argsparser.add_argument("-q", "--quiet", help="Keep quiet", action='store_false')
    argsparser.add_argument("--deep", help="How deep should download", default=1, type=int)

    argsparser.add_argument("--index", help="Where generate HTML index.", default="./alx/index.html", type=Path)
    argsparser.add_argument("--readme", help="Where generate README.", default="./alx/README.md", type=Path)
    argsparser.add_argument("--database", help="Path to database file.", default="./alx/database.json", type=Path)
    argsparser.add_argument("--files", help="Path to websites dir.", default="./alx/websites", type=Path)
    argsparser.add_argument("--screenshots", help="Path to screenshots dir.", default="./alx/screenshots", type=Path)
    args = argsparser.parse_args()

    main(args)
