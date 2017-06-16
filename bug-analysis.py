#! /usr/bin/env python
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# nova_bugs.py pulls out all the bugs from the nova project in
# launchpad and writes them to a file in JSON format.  This is based on
# infra_bugday.py from the CI team

import argparse
import ConfigParser
import datetime
import glob
import json
import logging
import os
import re
import sys

from launchpadlib.launchpad import Launchpad
import requests
import watson_developer_cloud
import watson_developer_cloud.natural_language_understanding.features.v1 as features

LPCACHEDIR = os.path.expanduser(os.environ.get('LPCACHEDIR',
                                               '~/.launchpadlib/cache'))
LPSTATUS = ('New', 'Confirmed', 'Triaged', 'In Progress', 'Incomplete')
LPIMPORTANCE = ('Critical', 'High', 'Medium', 'Undecided', 'Low', 'Wishlist')

RE_LINK = re.compile(' https://review.openstack.org/(\d+)')

LOG = logging.getLogger('bug-analysis')

def parse_args():
    parser = argparse.ArgumentParser(
        description="Do watson analysis on open bugs for project")
    parser.add_argument('--project', required=True,
                        help='The project to act on')
    parser.add_argument('--skip-lp', action="store_true", default=False,
                        help='Skip Launchpad Processing')
    parser.add_argument('-v', '--verbose', action="store_true", default=False)
    return parser.parse_args()


def collect_bugs(project):
    launchpad = Launchpad.login_anonymously('Watson Bug Learn',
                                            'production',
                                            LPCACHEDIR)
    project = launchpad.projects[project]

    for task in project.searchTasks(status=LPSTATUS,
                                    omit_duplicates=True,
                                    order_by='-importance'):
        bug = launchpad.load(task.bug_link)
        nova_status = 'Unknown'
        nova_owner = 'Unknown'
        comments = ""
        for m in bug.messages:
            comments += m.content + "\n\n"


        for task in bug.bug_tasks:
            if task.bug_target_name == 'devstack':
                nova_status = task.status
                nova_owner = task.assignee
                break
        title = bug.title.replace('"', "'")
        title = title.replace("\n", "")
        title = title.replace("\t", "")
        bug_data = {
            "id": bug.id,
            "importance": task.importance,
            "status": nova_status,
            "owner": str(nova_owner),
            "title": title,
            "link": task.web_link,
            "comments": unicode(comments),
            "tags": bug.tags
        }
        num = bug_data["link"].split("/")[-1]
        LOG.debug("Captured data for bug %s" % bug.id)
        try:
            with open('work/bug-%s.json' % num, 'w') as f:
                f.write(json.dumps(bug_data, indent=4))
        except ValueError, e:
            print e, bug_data


def get_auth():
    config = ConfigParser.RawConfigParser()
    config.read('auth.cfg')
    user = config.get('watson', 'username')
    password = config.get('watson', 'password')
    return (user, password)


def setup_logger(verbose):
    ch = logging.StreamHandler(sys.stdout)
    if verbose:
        ch.setLevel(logging.DEBUG)
        LOG.setLevel(logging.DEBUG)
    else:
        ch.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)-15s - %(name)s:[%(levelname)s] %(message)s')
    ch.setFormatter(formatter)
    LOG.addHandler(ch)


def run_watson_nlu():
    files = glob.glob('work/bug-*.json')
    (user, passwd) = get_auth()
    for fname in files:
        with open(fname) as f:
            LOG.debug("Processing %s" % fname)
            bug = json.loads(f.read())
            num = bug["link"].split("/")[-1]
            with open("work/res-%s.json" % num, "w") as out:
                nlu = watson_developer_cloud.NaturalLanguageUnderstandingV1(
                    version='2017-02-27',
                    username=user,
                    password=passwd)
                res = nlu.analyze(
                    text=bug["comments"],
                    features=[
                        features.Concepts(),
                        features.Keywords(),
                        features.Emotion(),
                        features.Sentiment(),
                    ])
                output = {"link": bug["link"],
                          "tags": bug["tags"],
                          "importance": bug["importance"],
                          "length": len(bug["comments"]),
                          "results": res}
                out.write(json.dumps(output, indent=4))


def keyword_analysis(bugs):
    report = "watson-keywords.html"
    keywords = {}
    for res in bugs:
        link = res["link"]
        for k in res["results"]["keywords"]:
            key = k["text"]
            if k["relevance"] >= 0.5:
                if key not in keywords:
                    keywords[key] = [link]
                else:
                    keywords[key].append(link)
    with open(report, "w") as f:
        f.write("""<html>
    <style>
    tr {vertical-align: top}
    td {padding: 0.5em}
    tr:nth-child(even) {background: #eee}
    .col1 {max-width: 100px}
    .col2 {width: 80%}
    </style>

    <body>
    <h1>Watson Keyword Analsysis of Open Nova Bugs</h1>

    This analysis was done by concatenating all the comment text for
    every bug in question, then running it through Watson's text
    analytics (base model, no additional training). Keywords that
    scored < 0.5 relevance were dropped.

    <table>
    <tr><th>Keyword</th><th>Reviews</th></tr>
    """)
        sort = keywords.items()
        for k, v in sorted(sort, key=(lambda x: (-len(x[1]), x[0]))):
            f.write("<tr><td class='col1'>{0}</td><td class='col2'>".format(k.encode("utf-8")))
            for bug in v:
                f.write('<a href="%s">%s</a>\n' % (bug, bug.split("/")[-1]))
            f.write("</td></tr>\n")
        f.write("""</table>
        </body>
        </html>
        """)

def concept_analysis(bugs):
    report = "watson-concept.html"
    keywords = {}
    concepts = {}
    for res in bugs:
        link = res["link"]
        for k in res["results"]["concepts"]:
            key = k["text"]
            concepts[key] = k["dbpedia_resource"]
            if k["relevance"] >= 0.5:
                if key not in keywords:
                    keywords[key] = [link]
                else:
                    keywords[key].append(link)
    with open(report, "w") as f:
        f.write("""<html>
    <style>
    tr {vertical-align: top}
    td {padding: 0.5em}
    tr:nth-child(even) {background: #eee}
    .col1 {max-width: 100px}
    .col2 {width: 80%}
    </style>

    <body>
    <h1>Watson Concept Analsysis of Open Nova Bugs</h1>

    This analysis was done by concatenating all the comment text for
    every bug in question, then running it through Watson's text
    analytics (base model, no additional training). Keywords that
    scored < 0.5 relevance were dropped.

    <table>
    <tr><th>Concept</th><th>Reviews</th></tr>
    """)
        sort = keywords.items()
        for k, v in sorted(sort, key=(lambda x: (-len(x[1]), x[0]))):
            f.write("<tr><td class='col1'><a href='{0}'>{1}</td><td class='col2'>".format(
                concepts[k].encode("utf-8"),
                k.encode("utf-8")))
            for bug in v:
                f.write('<a href="%s">%s</a>\n' % (bug, bug.split("/")[-1]))
            f.write("</td></tr>\n")
        f.write("""</table>
        </body>
        </html>
        """)


def sentiment_analysis(bugs):
    report = "watson-sentiment.html"
    sentiments = []
    for res in bugs:
        link = res["link"]
        sentiments.append(
            (link, res["results"]["sentiment"]["document"]["score"], res["importance"]))
        # sentiments[link] = res["results"]["sentiment"]["document"]["score"]
    with open(report, "w") as f:
        f.write("""<html>
    <style>
    tr {vertical-align: top}
    td {padding: 0.5em}
    tr:nth-child(even) {background: #eee}
    .col1 {max-width: 100px}
    .col2 {width: 80%}
    </style>

    <body>
    <h1>Watson Sentiment Analsysis of Open Nova Bugs</h1>

    This analysis was done by concatenating all the comment text for
    every bug in question, then running it through Watson's text
    analytics (base model, no additional training). Bugs are ranked by
    sentiment from most negative to most possitve.

    <table>
    <tr><th>Sentiment</th><th>Importance</th><th>Bug</th></tr>
    """)
        for x in sorted(sentiments, key=(lambda x: x[1])):
            f.write("<tr><td class='col1'>{0}</td><td>{1}</td><td class='col2'>".format(x[1], x[2]))
            bug = x[0]
            f.write('<a href="%s">%s</a>\n' % (bug, bug.split("/")[-1]))
            f.write("</td></tr>\n")
        f.write("""</table>
        </body>
        </html>
        """)


def main():
    args = parse_args()
    setup_logger(args.verbose)
    if not args.skip_lp:
        collect_bugs(args.project)
    run_watson_nlu()

    bugs = []
    for fname in glob.glob('work/res-*.json'):
        with open(fname) as f:
            res = json.loads(f.read())
            bugs.append(res)

    keyword_analysis(bugs)
    concept_analysis(bugs)
    sentiment_analysis(bugs)


if __name__ == "__main__":
    main()
