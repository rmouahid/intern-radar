"""A fixed vocabulary of technical skills, detected without any LLM call.

Each skill has a canonical name, a category and a regular expression of its
usual spellings. Offers and the candidate profile are matched against the
same vocabulary, so "what offers ask for" and "what the profile shows" can
be compared deterministically.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    name: str
    category: str
    pattern: re.Pattern[str]


def _skill(name: str, category: str, *aliases: str) -> Skill:
    spellings = aliases or (re.escape(name),)
    # Word boundaries that also work around symbols (C++, C#, .NET, Node.js).
    regex = r"(?<![\w+#.])(?:" + "|".join(spellings) + r")(?![\w+#])"
    return Skill(name, category, re.compile(regex, re.IGNORECASE))


LANG, ML, LLM, DATA, CLOUD, WEB, ENG, MATH = (
    "Langages",
    "Machine learning",
    "LLM et agents",
    "Données",
    "Cloud et MLOps",
    "Web et API",
    "Génie logiciel",
    "Maths et méthodes",
)

VOCABULARY: tuple[Skill, ...] = (
    # Languages
    _skill("Python", LANG),
    _skill("Java", LANG, r"java(?!\s*script)"),
    _skill("JavaScript", LANG, r"javascript", r"\bJS\b"),
    _skill("TypeScript", LANG),
    _skill("C++", LANG, r"c\+\+", r"(?<!-)cpp(?!-)"),
    _skill("C#", LANG, r"c#", r"\.net"),
    _skill("Go", LANG, r"golang", r"Go(?= (?:language|developer|programming))"),
    _skill("Rust", LANG),
    _skill("Scala", LANG),
    _skill("Kotlin", LANG),
    _skill("R", LANG, r"R(?= (?:language|programming|studio))", r"RStudio"),
    _skill("Julia", LANG),
    _skill("MATLAB", LANG),
    _skill("SQL", LANG, r"sql"),
    _skill("Bash", LANG, r"bash", r"shell scripting"),
    _skill("CUDA", LANG),
    # Machine learning
    _skill("PyTorch", ML, r"pytorch", r"torch"),
    _skill("TensorFlow", ML, r"tensorflow"),
    _skill("JAX", ML),
    _skill("Keras", ML),
    _skill("scikit-learn", ML, r"scikit-?learn", r"sklearn"),
    _skill("XGBoost", ML, r"xgboost", r"lightgbm", r"catboost"),
    _skill("Deep learning", ML, r"deep learning", r"neural networks?"),
    _skill(
        "Computer vision", ML, r"computer vision", r"image (?:recognition|segmentation)"
    ),
    _skill("NLP", ML, r"nlp", r"natural language processing"),
    _skill("Reinforcement learning", ML, r"reinforcement learning", r"\bRLHF\b"),
    _skill("Recommender systems", ML, r"recommend(?:er|ation) systems?"),
    _skill("Time series", ML, r"time[- ]series", r"forecasting"),
    _skill("Hugging Face", ML, r"hugging ?face", r"transformers library"),
    _skill("ONNX", ML),
    _skill("Model evaluation", ML, r"model evaluation", r"evals?\b", r"benchmarking"),
    _skill("Fine-tuning", ML, r"fine-?tuning", r"\bLoRA\b", r"\bPEFT\b"),
    _skill(
        "Distributed training", ML, r"distributed training", r"deepspeed", r"\bFSDP\b"
    ),
    # LLMs and agents
    _skill("LLM", LLM, r"llms?", r"large language models?"),
    _skill("RAG", LLM, r"rag", r"retrieval[- ]augmented"),
    _skill("Agents", LLM, r"(?:ai|llm|autonomous|multi-) ?agents?", r"agentic"),
    _skill("Prompt engineering", LLM, r"prompt(?:ing| engineering)"),
    _skill("LangChain", LLM, r"langchain", r"langgraph"),
    _skill("LlamaIndex", LLM, r"llama-?index"),
    _skill(
        "Vector databases",
        LLM,
        r"vector (?:databases?|search|stores?)",
        r"faiss",
        r"pinecone",
        r"weaviate",
        r"qdrant",
        r"milvus",
        r"pgvector",
        r"chroma(?:db)?",
    ),  # fmt: skip
    _skill("Embeddings", LLM, r"embeddings?", r"sentence-transformers"),
    _skill("OpenAI API", LLM, r"openai"),
    _skill("MCP", LLM, r"\bMCP\b", r"model context protocol"),
    _skill(
        "Inference optimisation",
        LLM,
        r"vllm",
        r"tensorrt",
        r"quantization",
        r"inference optimi[sz]ation",
        r"llama[.-]cpp",
    ),  # fmt: skip
    _skill("Multimodal", LLM, r"multi-?modal", r"vision-language"),
    # Data
    _skill("Pandas", DATA, r"pandas"),
    _skill("NumPy", DATA, r"numpy"),
    _skill("Spark", DATA, r"spark", r"pyspark", r"databricks"),
    _skill("Kafka", DATA),
    _skill("Airflow", DATA, r"airflow", r"dagster", r"prefect"),
    _skill("dbt", DATA, r"dbt"),
    _skill("Data pipelines", DATA, r"data pipelines?", r"\bETL\b", r"\bELT\b"),
    _skill("PostgreSQL", DATA, r"postgres(?:ql)?"),
    _skill("MongoDB", DATA, r"mongo(?:db)?"),
    _skill("Snowflake", DATA),
    _skill("BigQuery", DATA, r"bigquery"),
    _skill("Elasticsearch", DATA, r"elastic ?search", r"opensearch"),
    _skill("Redis", DATA),
    _skill(
        "Data visualisation", DATA, r"tableau", r"power ?bi", r"data visuali[sz]ation"
    ),
    # Cloud and MLOps
    _skill("AWS", CLOUD, r"aws", r"amazon web services", r"sagemaker"),
    _skill("Azure", CLOUD, r"azure"),
    _skill("GCP", CLOUD, r"gcp", r"google cloud", r"vertex ai"),
    _skill("Docker", CLOUD, r"docker", r"containers?"),
    _skill("Kubernetes", CLOUD, r"kubernetes", r"\bk8s\b"),
    _skill("Terraform", CLOUD, r"terraform", r"infrastructure as code"),
    _skill(
        "CI/CD",
        CLOUD,
        r"ci/cd",
        r"continuous integration",
        r"github actions",
        r"gitlab ci",
        r"jenkins",
    ),  # fmt: skip
    _skill(
        "MLOps",
        CLOUD,
        r"mlops",
        r"mlflow",
        r"weights (?:&|and) biases",
        r"kubeflow",
        r"model deployment",
    ),  # fmt: skip
    _skill("Linux", CLOUD, r"linux", r"unix"),
    _skill("Monitoring", CLOUD, r"prometheus", r"grafana", r"observability"),
    # Web and APIs
    _skill("REST APIs", WEB, r"rest(?:ful)? apis?", r"\bAPIs?\b"),
    _skill("FastAPI", WEB, r"fastapi"),
    _skill("Flask", WEB),
    _skill("Django", WEB),
    _skill("Node.js", WEB, r"node(?:\.js|js)?(?= |,|/|\.|$)", r"express(?:\.js)?"),
    _skill("React", WEB, r"react(?:\.js)?"),
    _skill("GraphQL", WEB, r"graphql"),
    _skill("gRPC", WEB, r"grpc"),
    _skill("Microservices", WEB, r"micro-?services?"),
    # Software engineering
    _skill("Git", ENG, r"git(?:hub|lab)?"),
    _skill("Testing", ENG, r"unit tests?", r"testing", r"pytest", r"junit", r"\bTDD\b"),
    _skill("Agile", ENG, r"agile", r"scrum", r"kanban"),
    _skill(
        "System design",
        ENG,
        r"system design",
        r"distributed systems",
        r"software architecture",
        r"scalab(?:le|ility)",
    ),  # fmt: skip
    _skill("Algorithms", ENG, r"algorithms?", r"data structures"),
    _skill(
        "Object-oriented design",
        ENG,
        r"object[- ]oriented",
        r"\bOOP\b",
        r"design patterns",
    ),  # fmt: skip
    _skill("Security", ENG, r"security", r"cryptograph\w*"),
    _skill(
        "Performance",
        ENG,
        r"performance (?:optimi[sz]ation|tuning)",
        r"profiling",
        r"low[- ]latency",
    ),  # fmt: skip
    # Maths and methods
    _skill("Statistics", MATH, r"statistic(?:s|al)", r"probabilit(?:y|ies)"),
    _skill("Linear algebra", MATH, r"linear algebra"),
    _skill("Optimisation", MATH, r"optimi[sz]ation", r"operations research"),
    _skill("A/B testing", MATH, r"a/b test(?:s|ing)?", r"experimentation"),
    _skill(
        "Research papers",
        MATH,
        r"publications?",
        r"research papers?",
        r"neurips",
        r"icml",
        r"iclr",
        r"\bACL\b",
        r"cvpr",
    ),  # fmt: skip
)

BY_NAME = {skill.name: skill for skill in VOCABULARY}


def find_skills(text: str) -> set[str]:
    """Canonical names of the vocabulary skills mentioned in `text`."""
    return {skill.name for skill in VOCABULARY if skill.pattern.search(text)}
