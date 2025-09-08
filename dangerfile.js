// dangerfile.js
import { danger, markdown, warn } from "danger";


// Check that Jira issue is assigned
// PR contains only 1 jira issue assigned
const title = danger.github.pr.title || "";
const JIRA_KEY = "MPT";
const JIRA_URL = "https://softwareone.atlassian.net/browse";
const re = new RegExp(`\\b${JIRA_KEY}-\\d+\\b`, "g");

const matches = title.match(re) || [];

if (matches.length === 0) {
  warn(`PR title must include exactly one Jira issue key in the format ${JIRA_KEY}-XXXX.`);
} else if (matches.length > 1) {
  warn(
    `PR title contains multiple Jira issue keys: ${matches.join(", ")}. ` +
    `Please keep only one.`
  );
} else {
  const issue = matches[0];
  const link = `${JIRA_URL}/${issue}`;
  markdown(`✅ Found Jira issue key in the title: [${issue}](${link})`);
}


// Сheck that PR doesn't contain more than 400 lines
const THRESHOLD = 400;

const { additions = 0, deletions = 0, changed_files = 0 } = danger.github.pr;
const totalChanged = additions + deletions;

if (totalChanged > THRESHOLD) {
  warn(
    `This PR changes **${totalChanged}** lines across **${changed_files}** files ` +
    `(threshold: ${THRESHOLD}). Please consider splitting it into smaller PRs for easier review.`
  );
}
