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
import datetime
import json
import os
import re
import sys

from launchpadlib.launchpad import Launchpad

LPCACHEDIR = os.path.expanduser(os.environ.get('LPCACHEDIR',
                                               '~/.launchpadlib/cache'))

LPPROJECT = os.environ.get('LPPROJECT',
                           'nova')

ALL_STATUS = ["New",
              "Incomplete",
              "Opinion",
              "Invalid",
              "Won't Fix",
              "Expired",
              "Confirmed",
              "Triaged",
              "In Progress",
              "Fix Committed",
              "Fix Released"]

LPSTATUS = ('New', 'Confirmed', 'Triaged', 'In Progress', 'Incomplete')
LPIMPORTANCE = ('Critical', 'High', 'Medium', 'Undecided', 'Low', 'Wishlist')

RE_LINK = re.compile(' https://review.openstack.org/(\d+)')

def parse_args():
    parser = argparse.ArgumentParser(
        description="Do watson analysis on open bugs for project")
    parser.add_argument('--project', required=True,
                        help='The project to act on')
    return parser.parse_args()

def safe_owner(message):
    try:
        return str(message.owner)
    except Exception:
        return ""

def bug_file(project, bug):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    return 'bugs/%s/%s/bug-%s.json' % (project, today, bug.id)

def collect_bugs(project_name):
    launchpad = Launchpad.login_anonymously('Bug Learn',
                                            'production',
                                            LPCACHEDIR)
    project = launchpad.projects[project_name]

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    counter = 0

    for task in project.searchTasks(status=ALL_STATUS,
                                    omit_duplicates=True,
                                    order_by='-importance'):
        bug = launchpad.load(task.bug_link)
        fname = bug_file(project_name, bug)
        if os.path.exists(fname):
            print("Already fetched: %s" % fname)
            continue

        nova_status = 'Unknown'
        nova_owner = 'Unknown'
        nova_openned = None
        nova_closed = None
        comments = []
        for m in bug.messages:
            comments.append(
                {"author": safe_owner(m),
                 "content": unicode(m.content),
                 "date_created": str(m.date_created)
                 })


        for task in bug.bug_tasks:
            if task.bug_target_name == project_name:
                nova_status = task.status
                nova_owner = task.assignee
                nova_openned = task.date_created
                nova_closed = task.date_closed
                break
        title = bug.title.replace('"', "'")
        title = title.replace("\n", "")
        title = title.replace("\t", "")
        bug_data = {
            "index": counter,
            "id": bug.id,
            "created": str(bug.date_created),
            "last_updated": str(bug.date_last_updated),
            "heat": bug.heat,
            "importance": task.importance,
            "status": nova_status,
            "owner": str(nova_owner),
            "title": title,
            "link": task.web_link,
            "description": bug.description,
            "comments": comments,
            "tags": bug.tags
        }
        if nova_openned:
            bug_data['openned'] = str(nova_openned)
        if nova_closed:
            bug_data['closed'] = str(nova_closed)

        try:
            path = fname
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with open(path, 'w') as f:
                f.write(json.dumps(bug_data, indent=4))
        except ValueError as e:
            print(e, bug_data)
        counter += 1
        print("Fetched: %s (%d)" % (bug_data["link"], counter))

def main():
    args = parse_args()
    collect_bugs(args.project)


if __name__ == "__main__":
    main()
