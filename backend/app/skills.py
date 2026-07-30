"""Curated skill dictionary and a deterministic, alias-aware skill detector.

SKILLS maps a canonical display name to the exact lowercase search terms that
should resolve to it. Aliases are explicit (the canonical is NOT auto-added), so
ambiguous English words are never matched by accident: "REST" is found via
"rest api"/"restful", never a bare "rest"; ".NET" via ".net"/"dotnet", and so
on. Real-world variants the tailoring research calls out are modeled directly:
k8s<->kubernetes, js<->javascript, ts<->typescript, gcp<->google cloud, ci/cd,
postgres<->postgresql, and more.

find_skills() matches case-insensitively with sensible boundaries so a short
token can never hit inside a larger word (no "r" inside "structure", no "go"
inside "google", no "c" inside "soccer"), while single-letter languages
(C, R, Go) still match when they stand alone. A second tier gates the aliases
that are ALSO ordinary English words ("go", "spring", "helm", "confluence",
...) behind a nearby tech-context signal, so the report never lies by counting
"go the extra mile" as the Go language (see the two-tier note below).
"""

import re
from bisect import bisect_right

# Canonical display name -> lowercase search terms that map to it.
SKILLS: dict[str, list[str]] = {
    # --- Programming languages ---
    "Python": ["python"],
    "JavaScript": ["javascript", "js", "ecmascript"],
    "TypeScript": ["typescript", "ts"],
    "Java": ["java"],
    "C": ["c"],
    "C++": ["c++", "cpp"],
    "C#": ["c#", "c sharp", "csharp"],
    "Go": ["go", "golang"],
    "Rust": ["rust"],
    "Ruby": ["ruby"],
    "PHP": ["php"],
    "Swift": ["swift"],
    "Kotlin": ["kotlin"],
    "Scala": ["scala"],
    "R": ["r"],
    "MATLAB": ["matlab"],
    "Perl": ["perl"],
    "Objective-C": ["objective-c", "objective c", "objc"],
    "Dart": ["dart"],
    "Elixir": ["elixir"],
    "Haskell": ["haskell"],
    "Clojure": ["clojure"],
    "Groovy": ["groovy"],
    "Lua": ["lua"],
    "Julia": ["julia"],
    "Bash": ["bash", "shell scripting", "shell script", "shell scripts"],
    "PowerShell": ["powershell"],
    "SQL": ["sql"],
    "HTML": ["html", "html5"],
    "CSS": ["css", "css3"],
    "Sass": ["sass", "scss"],
    "F#": ["f#", "fsharp"],
    "Visual Basic": ["visual basic", "vb.net", "vba"],
    "COBOL": ["cobol"],
    "Fortran": ["fortran"],
    "Solidity": ["solidity"],
    "Assembly": ["assembly language"],
    # --- Frontend frameworks and libraries ---
    "React": ["react", "react.js", "reactjs"],
    "Angular": ["angular", "angular.js", "angularjs"],
    "Vue.js": ["vue", "vue.js", "vuejs"],
    "Svelte": ["svelte", "sveltekit"],
    "Next.js": ["next.js", "nextjs"],
    "Nuxt": ["nuxt", "nuxt.js", "nuxtjs"],
    "jQuery": ["jquery"],
    "Redux": ["redux"],
    "Tailwind CSS": ["tailwind", "tailwind css", "tailwindcss"],
    "Bootstrap": ["bootstrap"],
    "Material UI": ["material ui", "material-ui", "mui"],
    "Webpack": ["webpack"],
    "Vite": ["vite"],
    "Babel": ["babel"],
    "Ember.js": ["ember", "ember.js", "emberjs"],
    "Backbone.js": ["backbone", "backbone.js"],
    "Gatsby": ["gatsby"],
    "Three.js": ["three.js", "threejs"],
    "Storybook": ["storybook"],
    # --- Backend and web frameworks ---
    "Node.js": ["node", "node.js", "nodejs"],
    "Express.js": ["express", "express.js", "expressjs"],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Spring": ["spring", "spring boot", "spring framework", "spring mvc"],
    "Laravel": ["laravel"],
    "Ruby on Rails": ["ruby on rails", "rails"],
    "ASP.NET": ["asp.net", "aspnet", "asp.net core"],
    ".NET": [".net", "dotnet", ".net core"],
    "Symfony": ["symfony"],
    "NestJS": ["nestjs", "nest.js"],
    "GraphQL": ["graphql"],
    "gRPC": ["grpc"],
    "REST": ["rest api", "rest apis", "restful", "restful api"],
    "SOAP": ["soap api"],
    "WebSocket": ["websocket", "websockets"],
    # --- Mobile ---
    "Flutter": ["flutter"],
    "React Native": ["react native", "react-native"],
    "Android": ["android"],
    "iOS": ["ios"],
    "Xamarin": ["xamarin"],
    "Ionic": ["ionic"],
    "SwiftUI": ["swiftui"],
    "Jetpack Compose": ["jetpack compose"],
    # --- Databases and data stores ---
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "MySQL": ["mysql"],
    "SQLite": ["sqlite"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Oracle Database": ["oracle database", "oracle db"],
    "Microsoft SQL Server": ["sql server", "mssql", "microsoft sql server"],
    "MariaDB": ["mariadb"],
    "Cassandra": ["cassandra"],
    "DynamoDB": ["dynamodb"],
    "Elasticsearch": ["elasticsearch", "elastic search"],
    "Neo4j": ["neo4j"],
    "Couchbase": ["couchbase"],
    "CouchDB": ["couchdb"],
    "Firebase": ["firebase"],
    "Firestore": ["firestore"],
    "Supabase": ["supabase"],
    "Snowflake": ["snowflake"],
    "BigQuery": ["bigquery", "big query"],
    "Redshift": ["redshift"],
    "InfluxDB": ["influxdb"],
    "Memcached": ["memcached"],
    "pgvector": ["pgvector"],
    "CockroachDB": ["cockroachdb"],
    # --- Cloud platforms and managed services ---
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure", "microsoft azure"],
    "Google Cloud": ["google cloud", "gcp", "google cloud platform"],
    "Amazon S3": ["s3", "amazon s3"],
    "Amazon EC2": ["ec2", "amazon ec2"],
    # Only the qualified "aws lambda": a bare "lambda"/"lambda functions"
    # almost always means a Python/JS lambda, not the AWS product.
    "AWS Lambda": ["aws lambda"],
    "Amazon RDS": ["rds", "amazon rds"],
    "Heroku": ["heroku"],
    "DigitalOcean": ["digitalocean", "digital ocean"],
    "Vercel": ["vercel"],
    "Netlify": ["netlify"],
    "Cloudflare": ["cloudflare"],
    "Render": ["render.com"],
    "Oracle Cloud": ["oracle cloud", "oci"],
    "IBM Cloud": ["ibm cloud"],
    "Linode": ["linode"],
    "Fly.io": ["fly.io"],
    "Amazon SQS": ["amazon sqs", "sqs"],
    "Amazon SNS": ["amazon sns", "sns"],
    "Google Kubernetes Engine": ["gke", "google kubernetes engine"],
    "Amazon EKS": ["eks", "amazon eks"],
    "Azure DevOps": ["azure devops"],
    "AWS CloudFormation": ["cloudformation", "aws cloudformation"],
    "Amazon SageMaker": ["sagemaker", "amazon sagemaker"],
    # --- DevOps, infrastructure, observability ---
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "Ansible": ["ansible"],
    "Jenkins": ["jenkins"],
    "CI/CD": [
        "ci/cd", "cicd", "ci-cd",
        "continuous integration", "continuous delivery", "continuous deployment",
    ],
    "GitHub Actions": ["github actions"],
    "GitLab CI": ["gitlab ci", "gitlab ci/cd"],
    "CircleCI": ["circleci", "circle ci"],
    "Travis CI": ["travis ci", "travisci"],
    "Helm": ["helm"],
    "Prometheus": ["prometheus"],
    "Grafana": ["grafana"],
    "Nginx": ["nginx"],
    "Apache HTTP Server": ["apache http server", "apache httpd"],
    "Vagrant": ["vagrant"],
    "Puppet": ["puppet"],
    "Pulumi": ["pulumi"],
    "ArgoCD": ["argocd", "argo cd"],
    "Datadog": ["datadog"],
    "Splunk": ["splunk"],
    "New Relic": ["new relic"],
    "PagerDuty": ["pagerduty"],
    "Sentry": ["sentry"],
    "OpenShift": ["openshift"],
    "Consul": ["consul"],
    "HashiCorp Vault": ["hashicorp vault"],
    "Istio": ["istio"],
    "Apache Kafka": ["kafka", "apache kafka"],
    "RabbitMQ": ["rabbitmq"],
    "Celery": ["celery"],
    "Apache Flink": ["apache flink", "flink"],
    "ELK Stack": ["elk stack", "elk"],
    # --- Data, analytics, machine learning ---
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "SciPy": ["scipy"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "TensorFlow": ["tensorflow"],
    "PyTorch": ["pytorch"],
    "Keras": ["keras"],
    "Matplotlib": ["matplotlib"],
    "Seaborn": ["seaborn"],
    "Apache Spark": ["apache spark", "spark", "pyspark"],
    "Hadoop": ["hadoop"],
    "Airflow": ["airflow", "apache airflow"],
    "dbt": ["dbt"],
    "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"],
    "Looker": ["looker"],
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning"],
    "Natural Language Processing": ["natural language processing", "nlp"],
    "Computer Vision": ["computer vision"],
    "Data Science": ["data science"],
    "Data Analysis": ["data analysis", "data analytics"],
    "Data Engineering": ["data engineering"],
    "ETL": ["etl"],
    "OpenCV": ["opencv"],
    "Hugging Face": ["hugging face", "huggingface"],
    "LangChain": ["langchain"],
    "OpenAI API": ["openai api"],
    "Jupyter": ["jupyter", "jupyter notebook"],
    "XGBoost": ["xgboost"],
    "MLOps": ["mlops"],
    # --- Testing ---
    "Jest": ["jest"],
    "Mocha": ["mocha"],
    "Cypress": ["cypress"],
    "Selenium": ["selenium"],
    "Playwright": ["playwright"],
    "pytest": ["pytest"],
    "JUnit": ["junit"],
    "Vitest": ["vitest"],
    "Testing Library": ["testing library", "react testing library"],
    "Postman": ["postman"],
    "Cucumber": ["cucumber"],
    "Puppeteer": ["puppeteer"],
    # --- Version control, tools, collaboration ---
    "Git": ["git"],
    "GitHub": ["github"],
    "GitLab": ["gitlab"],
    "Bitbucket": ["bitbucket"],
    "Jira": ["jira"],
    "Confluence": ["confluence"],
    "Trello": ["trello"],
    "Asana": ["asana"],
    "Slack": ["slack"],
    "Notion": ["notion"],
    "Figma": ["figma"],
    "Sketch": ["sketch"],
    "Adobe XD": ["adobe xd"],
    "Linear": ["linear.app"],
    "Linux": ["linux"],
    "Unix": ["unix"],
    "Windows Server": ["windows server"],
    "macOS": ["macos"],
    "Vim": ["vim"],
    "VS Code": ["vs code", "visual studio code", "vscode"],
    "IntelliJ IDEA": ["intellij", "intellij idea"],
    "Eclipse": ["eclipse"],
    # --- Architecture, methods, concepts ---
    "Microservices": ["microservices", "microservice architecture"],
    "Serverless": ["serverless"],
    "OAuth": ["oauth", "oauth2", "oauth 2.0"],
    "JWT": ["jwt", "json web token", "json web tokens"],
    "OpenAPI": ["openapi", "swagger"],
    "WebRTC": ["webrtc"],
    "WebAssembly": ["webassembly", "wasm"],
    "Protocol Buffers": ["protocol buffers", "protobuf"],
    "Agile": ["agile"],
    "Scrum": ["scrum"],
    "Kanban": ["kanban"],
    "DevOps": ["devops"],
    "TDD": ["tdd", "test driven development", "test-driven development"],
    "BDD": ["bdd", "behavior driven development"],
    "Object-Oriented Programming": [
        "object-oriented programming", "object oriented programming", "oop",
    ],
    "Functional Programming": ["functional programming"],
    "Design Patterns": ["design patterns"],
    "System Design": ["system design"],
    "Data Structures": ["data structures"],
    "Algorithms": ["algorithms"],
    # --- Soft skills ---
    "Communication": ["communication", "communication skills"],
    "Leadership": ["leadership"],
    "Teamwork": ["teamwork", "team player"],
    "Problem Solving": ["problem solving", "problem-solving"],
    "Critical Thinking": ["critical thinking"],
    "Time Management": ["time management"],
    "Collaboration": ["collaboration"],
    "Adaptability": ["adaptability"],
    "Creativity": ["creativity"],
    "Attention to Detail": ["attention to detail"],
    "Project Management": ["project management"],
    "Analytical Skills": ["analytical skills", "analytical thinking"],
    "Mentoring": ["mentoring", "mentorship"],
    "Presentation Skills": ["presentation skills"],
    "Stakeholder Management": ["stakeholder management"],
    "Customer Service": ["customer service"],
    "Negotiation": ["negotiation"],
    "Public Speaking": ["public speaking"],
    "Conflict Resolution": ["conflict resolution"],
    "Emotional Intelligence": ["emotional intelligence"],
}


def _build_alias_map() -> dict[str, str]:
    """alias (lowercase) -> canonical. A duplicate alias is a dictionary bug."""
    mapping: dict[str, str] = {}
    for canonical, aliases in SKILLS.items():
        for alias in aliases:
            key = alias.lower()
            if key in mapping and mapping[key] != canonical:
                raise ValueError(
                    f"Alias {alias!r} maps to both {mapping[key]!r} and {canonical!r}"
                )
            mapping[key] = canonical
    return mapping


ALIAS_TO_CANONICAL: dict[str, str] = _build_alias_map()

# Boundaries reject a match that is glued to a letter, digit, "+" or "#", so
# "c"/"c++"/"c#" never bleed into one another and no short token hits inside a
# word. "." and "/" are intentionally NOT boundary characters, so ".net",
# "node.js" and "ci/cd" match, and a trailing "R." still finds R.
_LEFT = r"(?<![A-Za-z0-9+#])"
_RIGHT = r"(?![A-Za-z0-9+#])"
_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"\S+")

# One alternation, longest alias first, so the most specific term wins at any
# position ("javascript" before "java", "google cloud platform" before "gcp").
_ALIASES_LONGEST_FIRST = sorted(ALIAS_TO_CANONICAL, key=len, reverse=True)
_PATTERN = re.compile(
    _LEFT + r"(?:" + "|".join(re.escape(a) for a in _ALIASES_LONGEST_FIRST) + r")" + _RIGHT,
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Two-tier matching: a precision gate for ambiguous, English-word aliases.
#
# The within-word boundary above stops "go" hitting inside "google", but some
# alias forms ARE ordinary English on their own ("go the extra mile", "at the
# helm", "starting spring 2026", "a confluence of ideas", "R&D", "C-suite").
# Counting those on their plain-English meaning makes the report lie, so each
# such ALIAS is marked ambiguous and is kept ONLY when a disambiguating tech
# signal sits within a small window of tokens:
#   (a) a confirmed skill nearby - this propagates across a conjunction/list,
#       so "experience with Go and Rust" keeps Rust once Go is confirmed;
#   (b) a tech-context keyword nearby (developer, framework, experience, ...);
#   (c) it shares a delimited run (comma/slash/pipe list) with a confirmed
#       skill, which rescues long "Skills: Go, React, AWS" lists that reach
#       past the token window.
# With no signal the ambiguous hit is dropped: precision over recall for these
# terms specifically. Unambiguous skills - and clean multi-word forms like
# "spring boot", "apache spark", "ruby on rails", "swiftui", "aws lambda" -
# always count, so real usage keeps full recall.
#
# The keyword window is kept tight (3). "engineering" is a legitimate context
# keyword yet sits 4 tokens from "confluence" in the ordinary prose "a
# confluence of design and engineering", so a wider keyword window would
# re-introduce exactly that false positive.
# ---------------------------------------------------------------------------
_AMBIGUOUS_ALIASES = frozenset(
    {
        "c", "r", "go", "spring", "notion", "swift", "spark", "helm", "rails",
        "sketch", "eclipse", "confluence", "dart", "rust", "groovy", "elk",
    }
)

# Words that signal a technical context around an ambiguous term.
_CONTEXT_KEYWORDS = (
    "programming", "developer", "developers", "development", "developing",
    "engineer", "engineers", "engineering", "language", "languages",
    "framework", "frameworks", "library", "libraries", "stack", "proficient",
    "proficiency", "experience", "experienced", "expertise", "familiar",
    "familiarity", "skill", "skills", "technology", "technologies", "backend",
    "back-end", "frontend", "front-end", "full-stack", "fullstack",
    "microservice", "microservices", "api", "apis", "ci/cd", "version",
    "coding", "software",
)
_KEYWORD_RE = re.compile(
    _LEFT
    + r"(?:"
    + "|".join(re.escape(k) for k in sorted(_CONTEXT_KEYWORDS, key=len, reverse=True))
    + r")"
    + _RIGHT,
    re.IGNORECASE,
)

# A run of at least three short tech-ish tokens joined by list delimiters
# (comma / slash / pipe / semicolon / bullet). Ordinary prose rarely forms
# such a run, and (c) only fires when the run also holds a confirmed skill.
_LIST_RUN_RE = re.compile(
    r"(?:[A-Za-z0-9][\w+#./-]{0,24}\s*[,/|;•]\s*){2,}[A-Za-z0-9][\w+#./-]{0,24}"
)

_KW_WINDOW = 3
_SKILL_WINDOW = 4
# Sentence/line boundaries are HARD walls for the disambiguation window: a
# confirmed skill or keyword in one sentence must not vouch for an ambiguous
# word in the next. Real job posts constantly place actual skills in one
# sentence ("Required: Python, FastAPI.") and ordinary words in the next
# ("You must go the extra mile."), so without this wall "go"/"spring" leak in.
_SENTENCE_END_CHARS = (".", "!", "?")


def find_skills(text: str | None) -> list[str]:
    """Canonical skills present in text, in first-occurrence order, deduplicated.

    Matching is case-insensitive and alias-aware. Ambiguous English-word skills
    are gated by nearby tech context (see the two-tier note above), and that
    search never crosses a sentence or line boundary. Matching itself runs on
    whitespace-collapsed text, so a multi-word skill wrapped across a line still
    matches; only the ambiguity gate respects the boundaries.
    """
    if not text:
        return []
    # Raw tokens (from the original text) preserve the punctuation/newlines that
    # mark sentence breaks; the normalized string joins them with single spaces
    # so multi-word aliases match regardless of the original whitespace.
    raw_tokens = list(_TOKEN_RE.finditer(text))
    if not raw_tokens:
        return []
    tokens = [t.group(0) for t in raw_tokens]
    normalized = " ".join(tokens)
    barriers = _sentence_barriers(text, raw_tokens)

    token_starts: list[int] = []
    cursor = 0
    for token in tokens:
        token_starts.append(cursor)
        cursor += len(token) + 1  # + the joining space

    def token_index(pos: int) -> int:
        index = bisect_right(token_starts, pos) - 1
        return index if index >= 0 else 0

    matches: list[dict] = []
    for match in _PATTERN.finditer(normalized):
        alias = match.group(0).lower()
        ambiguous = alias in _AMBIGUOUS_ALIASES
        matches.append(
            {
                "start": match.start(),
                "ti": token_index(match.start()),
                "canonical": ALIAS_TO_CANONICAL[alias],
                "ambiguous": ambiguous,
                "confirmed": not ambiguous,  # unambiguous hits count immediately
            }
        )
    if any(m["ambiguous"] for m in matches):
        _confirm_ambiguous(matches, normalized, token_index, barriers)

    ordered: dict[str, None] = {}
    for match in matches:
        if match["confirmed"]:
            ordered.setdefault(match["canonical"], None)
    return list(ordered)


def _sentence_barriers(text: str, raw_tokens: list[re.Match]) -> set[int]:
    """Token indices i with a sentence/line break between token i and i+1.

    A break is either a token that ends in sentence punctuation (. ! ?) - so a
    trailing "." ends the sentence while "Node.js" or "3.5" does not - or a gap
    between two tokens that contains a newline.
    """
    barriers: set[int] = set()
    for i in range(len(raw_tokens) - 1):
        if raw_tokens[i].group(0)[-1] in _SENTENCE_END_CHARS:
            barriers.add(i)
            continue
        gap = text[raw_tokens[i].end() : raw_tokens[i + 1].start()]
        if "\n" in gap or "\r" in gap:
            barriers.add(i)
    return barriers


def _same_segment(a: int, b: int, barriers: set[int]) -> bool:
    """True when no sentence/line break sits between token indices a and b."""
    lo, hi = (a, b) if a <= b else (b, a)
    return not any(i in barriers for i in range(lo, hi))


def _confirm_ambiguous(
    matches: list[dict], normalized: str, token_index, barriers: set[int]
) -> None:
    """Confirm ambiguous matches that have a nearby, SAME-SENTENCE tech signal.

    Runs to a fixpoint so confirmation propagates within a sentence: once "Go"
    is confirmed by a keyword, an adjacent "Rust" is confirmed on the next pass
    by signal (a). Propagation cannot hop a sentence break because every signal
    check is gated by _same_segment.
    """
    keyword_tis = sorted(token_index(m.start()) for m in _KEYWORD_RE.finditer(normalized))
    runs = [(m.start(), m.end()) for m in _LIST_RUN_RE.finditer(normalized)]
    changed = True
    while changed:
        changed = False
        confirmed = [m for m in matches if m["confirmed"]]
        for match in matches:
            if match["confirmed"]:
                continue
            ti = match["ti"]
            # (b) a context keyword within the window and the same sentence.
            signal = any(
                abs(k - ti) <= _KW_WINDOW and _same_segment(k, ti, barriers)
                for k in keyword_tis
            )
            if not signal:  # (a) a confirmed skill within the window, same sentence.
                signal = any(
                    other is not match
                    and abs(other["ti"] - ti) <= _SKILL_WINDOW
                    and _same_segment(other["ti"], ti, barriers)
                    for other in confirmed
                )
            if not signal:  # (c) a delimited list holding a confirmed skill.
                signal = _in_delimited_run_with_skill(match, confirmed, runs, barriers)
            if signal:
                match["confirmed"] = True
                changed = True


def _in_delimited_run_with_skill(
    match: dict, confirmed: list[dict], runs: list[tuple[int, int]], barriers: set[int]
) -> bool:
    for run_start, run_end in runs:
        if run_start <= match["start"] < run_end:
            return any(
                other is not match
                and run_start <= other["start"] < run_end
                and _same_segment(other["ti"], match["ti"], barriers)
                for other in confirmed
            )
    return False
