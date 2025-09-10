import { danger, markdown, warn } from "danger";

const title = danger.github.pr.title || "";
const JIRA_KEY = "MPT";
const JIRA_URL = "https://softwareone.atlassian.net/browse";
const jiraRe = new RegExp(`\\b${JIRA_KEY}-\\d+\\b`, "g");
const THRESHOLD = 400;
const { additions = 0, deletions = 0, changed_files = 0 } = danger.github.pr;
const commits = danger.github.commits || [];
const baseBranch = danger.github.pr.base.ref || "";


// Check that Jira issue is assigned
// PR contains only 1 jira issue assigned
const matches = title.match(jiraRe) || [];

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
const totalChanged = additions + deletions;

if (totalChanged > THRESHOLD) {
  warn(
    `This PR changes **${totalChanged}** lines across **${changed_files}** files ` +
    `(threshold: ${THRESHOLD}). Please consider splitting it into smaller PRs for easier review.`
  );
}


// Check for multiple commits in the PR
const commitCount = commits.length;

if (commitCount > 1) {
  warn(
    `This PR contains **${commitCount} commits**.\n\n` +
    `Please squash them into a single commit to keep the git history clean and easy to follow.\n\n` +
    `Multiple commits are acceptable only in the following cases:\n` +
    `1. One commit is a technical refactoring, and another introduces business logic changes.\n` +
    `2. You are doing a complex multi-step refactoring (although in this case we still recommend splitting it into separate PRs).`
  );
}


// Check that release/* PRs contains [HF] or [Backport]
if (baseBranch.startsWith("release/")) {
  const hasRequiredTag = /\[(HF|Backport)\]/i.test(title);

  if (!hasRequiredTag) {
    warn(
      `PRs targeting a release branch (**${baseBranch}**) must include [HF] or [Backport] in the title.\n\n` +
      `Example: \`[HF] MPT-1234 Fix crash on startup\` or \`[Backport] MPT-1234 Update dependency versions\`.`
    );
  }
}


// Check if there are no any test files changes when there are code changes
const allModifiedFiles = [
  ...danger.git.modified_files,
  ...danger.git.created_files,
  ...danger.git.deleted_files
];

// Фильтруем тестовые файлы
const testChanges = allModifiedFiles.filter(f => f.startsWith("tests/"));
const codeChanges = allModifiedFiles.filter(f => !f.startsWith("tests/"));

if (codeChanges.length > 0 && testChanges.length === 0) {
  warn(
    `This PR modifies code (${codeChanges.length} file(s)) but does not include any changes in the **tests/** folder.\n\n` +
    `Please consider adding or updating tests to cover your changes.`
  );
}


// Check if the PR is opened to release/* branch that there is a corresponding
// PR merged or open to the main branch
const OWNER = danger.github.thisPR.owner;
const REPO  = danger.github.thisPR.repo;

if (baseBranch.startsWith("release/")) {
  const keys = Array.from(new Set(title.match(jiraRe) || []));

  if (keys.length === 0) {
    warn(
      `This PR targets **${baseBranch}**, but its title does not include a Jira issue key (expected format: ${JIRA_KEY}-XXXX).`
    );
  } else {
    schedule(checkKeysAgainstMain(keys));
  }
}

async function checkKeysAgainstMain(keys) {
  const api = danger.github.api;
  const rows = [];

  for (const key of keys) {
    const jiraLink = `[${key}](${JIRA_URL}/${key})`;

    // Search PRs in this repo that target main and mention the key in the title
    const qBase = `"${key}" repo:${OWNER}/${REPO} is:pr base:main`;
    const openRes = await api.search.issuesAndPullRequests({ q: `${qBase} is:open` });
    const closedRes = await api.search.issuesAndPullRequests({ q: `${qBase} is:closed` });

    const items = [...(openRes.data.items || []), ...(closedRes.data.items || [])];
    const numbers = Array.from(new Set(items.map(i => i.number).filter(Boolean)));

    const details = [];
    for (const number of numbers) {
      try {
        const { data: prData } = await api.pulls.get({
          owner: OWNER,
          repo: REPO,
          pull_number: number,
        });
        if (prData.base?.ref !== "main") continue;

        details.push({
          number,
          html_url: prData.html_url,
          status: prData.merged ? "merged" : prData.state === "open" ? "open" : "closed",
          title: prData.title || "",
        });
      } catch {
        // ignore individual fetch errors
      }
    }

    const valid = details.filter(d => d.status === "open" || d.status === "merged");

    if (valid.length === 0) {
      warn(
        `No PR to **main** found for Jira issue ${jiraLink}. ` +
        `Please create (or reference) a mainline PR for this change, or ensure it has already been merged.`
      );
      rows.push([jiraLink, "—", "not found"]);
    } else {
      const list = valid.map(v => `[${v.number}](${v.html_url}) (${v.status})`).join(", ");
      rows.push([jiraLink, list, "ok"]);
    }
  }

  if (rows.length) {
    const table = [
      "| Jira issue | PRs to main (open/merged) | Status |",
      "|---|---|---|",
      ...rows.map(r => `| ${r[0]} | ${r[1]} | ${r[2]} |`),
    ].join("\n");
    markdown(`### Release → Main linkage check\n${table}`);
  }
}


// Check that PR doesn't contain merge commits
if (commits.length > 0) {
  const mergeCommits = commits.filter(c =>
    (Array.isArray(c.parents) && c.parents.length > 1) ||
    /^merge\b/i.test(c.commit?.message || "")
  );

  if (mergeCommits.length > 0) {
    const list = mergeCommits
      .map(c => `- ${c.sha?.slice(0, 7) || "???????"} — ${c.commit?.message?.split("\n")[0] || "(no message)"}`)
      .join("\n");

    warn(
      `This PR contains ${mergeCommits.length} merge commit(s).\n` +
      `Please use \`git pull --rebase\` to keep a clean, linear history.\n\n` +
      `Offending commits:\n${list}`
    );
  }
}


// Check structure of added files, that every added file
// has corresponding test file
const added = danger.git.created_files || [];
const isInit = (p) => p.endsWith("__init__.py");

const addedTests = new Set(
  added.filter((p) => p.startsWith("tests/") && p.endsWith(".py") && !isInit(p))
);

const addedCode = added.filter(
  (p) => p.endsWith(".py") && !p.startsWith("tests/") && !isInit(p)
);

const mismatches = [];

for (const codePath of addedCode) {
  const parts = codePath.split("/");
  const hasRoot = parts.length >= 2;
  const fileName = parts[parts.length - 1];

  const expectedTestFile = `test_${fileName}`;

  const subdirs = hasRoot ? parts.slice(1, -1).join("/") : "";

  const expectedTestPath =
    "tests/" + (subdirs ? subdirs + "/" : "") + expectedTestFile;

  if (!addedTests.has(expectedTestPath)) {
    mismatches.push({
      code: codePath,
      expectedTest: expectedTestPath,
    });
  }
}

if (mismatches.length > 0) {
  warn(
    "Some newly added source files do not have corresponding tests in the `tests/` folder " +
      "with matching structure and the `test_` prefix."
  );

  const table = [
    "| Added source file | Expected test (added in this PR) |",
    "|---|---|",
    ...mismatches.map(
      (m) => `| \`${m.code}\` | \`${m.expectedTest}\` |`
    ),
  ].join("\n");

  markdown(`### Tests mirroring check (created files only)\n${table}`);
}
