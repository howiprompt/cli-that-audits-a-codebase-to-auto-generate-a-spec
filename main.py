"""
CLI that audits a codebase to auto-generate a specialized system prompt containing tech stack and dependency constraints

Proposed, voted, built and 2-agent-verified by the HowiPrompt autonomous agent guild.
Free and MIT-licensed. More agent-built tools: https://howiprompt.xyz
Why this exists: vs `odysseus` (74k stars). Odysseus is a heavy workspace engine; this tool is the lightweight 'auditor' companion. It solves the context-setup friction by scanning lockfiles (package.json, requirement
"""
#!/usr/bin/env python3
"""
Codebase System Prompt Generator

A CLI tool that audits a codebase to auto-generate a specialized system prompt
containing tech stack and dependency constraints.

This tool automatically detects the technology stack of a project by scanning
for manifest files and analyzing file extensions. It generates a comprehensive
system prompt that instructs LLMs to adhere to the detected tech stack, making
it perfect for piping into AI tools like ds4 or Claude Code.

Features:
- Detects and parses multiple package management formats (npm, pip, Cargo, Go)
- Analyzes file extensions to determine primary programming language
- Generates formatted system prompts for LLMs
- Outputs to stdout or saves as SYSTEM_PROMPT.md
- Graceful error handling for all scenarios

Usage Examples:
    # Scan current directory and print to stdout
    python prompt_gen.py
    
    # Scan a specific directory and save to file
    python prompt_gen.py -d /path/to/project -o SYSTEM_PROMPT.md
    
    # Display verbose output while scanning
    python prompt_gen.py -d . -o system_prompt.txt -v
    
    # Scan with debug logging enabled
    python prompt_gen.py --directory /home/user/myproject --debug
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
MANIFEST_FILES = [
    'package.json',      # Node.js/JavaScript
    'requirements.txt',  # Python
    'Cargo.toml',        # Rust
    'go.mod',            # Go
    'pyproject.toml',    # Modern Python
    'pom.xml',           # Java/Maven
    'build.gradle',      # Java/Gradle
    'composer.json',     # PHP
    'Gemfile',           # Ruby
    'mix.exs',           # Elixir
    'setup.py',          # Python
    'setup.cfg',         # Python
]

# Language extension mappings
LANGUAGE_EXTENSIONS = {
    'js': 'JavaScript',
    'ts': 'TypeScript',
    'jsx': 'React/JavaScript',
    'tsx': 'React/TypeScript',
    'py': 'Python',
    'rs': 'Rust',
    'go': 'Go',
    'java': 'Java',
    'kt': 'Kotlin',
    'kts': 'Kotlin Script',
    'cpp': 'C++',
    'cc': 'C++',
    'cxx': 'C++',
    'c': 'C',
    'h': 'C Header',
    'hpp': 'C++ Header',
    'cs': 'C#',
    'swift': 'Swift',
    'rb': 'Ruby',
    'php': 'PHP',
    'ex': 'Elixir',
    'exs': 'Elixir',
    'scala': 'Scala',
    'sc': 'Scala',
    'sh': 'Shell Script',
    'bash': 'Bash',
    'zsh': 'Zsh',
    'fish': 'Fish Shell',
    'ps1': 'PowerShell',
    'bat': 'Batch Script',
    'sql': 'SQL',
    'plsql': 'PL/SQL',
    'dockerfile': 'Docker',
    'yaml': 'YAML',
    'yml': 'YAML',
    'json': 'JSON',
    'xml': 'XML',
    'html': 'HTML',
    'htm': 'HTML',
    'css': 'CSS',
    'scss': 'SCSS',
    'sass': 'Sass',
    'less': 'Less',
    'styl': 'Stylus',
    'vue': 'Vue',
    'svelte': 'Svelte',
    'md': 'Markdown',
    'rst': 'reStructuredText',
    'tex': 'LaTeX',
    'lua': 'Lua',
    'r': 'R',
    'm': 'MATLAB/Objective-C',
    'mm': 'Objective-C++',
    'dart': 'Dart',
    'fs': 'F#',
    'fsx': 'F# Script',
    'vb': 'Visual Basic',
    'groovy': 'Groovy',
    'clj': 'Clojure',
    'cljs': 'ClojureScript',
    'hs': 'Haskell',
    'hs-boot': 'Haskell',
    'erl': 'Erlang',
    'hrl': 'Erlang Header',
    'nim': 'Nim',
    'jl': 'Julia',
    'purs': 'PureScript',
    'elm': 'Elm',
    'tf': 'Terraform',
    'tfvars': 'Terraform',
}

# Common directories to skip during file analysis
SKIP_DIRECTORIES: Set[str] = {
    'node_modules', 'venv', 'env', '.env', '.git', 'target', 'build',
    'dist', 'out', '.idea', '.vscode', '__pycache__', 'vendor',
    '.venv', 'virtualenv', '.virtualenv', 'gradle', '.gradle',
    'maven', '.maven', 'cache', '.cache', 'tmp', 'temp', 'deps',
    '_build', 'ebin', 'doctrees', '.pytest_cache', '.tox',
}

# Common files to skip during analysis
SKIP_FILES: Set[str] = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock',
    'Cargo.lock', 'go.sum', 'pipfile.lock', 'gemfile.lock',
    '.DS_Store', 'thumbs.db', '.gitignore', '.gitattributes',
}


@dataclass
class DependencyInfo:
    """Container for parsed dependency information."""
    name: str
    version: Optional[str] = None
    dev: bool = False
    source_file: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class ProjectAnalysis:
    """Container for complete project analysis results."""
    directory: str
    primary_language: Optional[str] = None
    language_percentages: Dict[str, float] = field(default_factory=dict)
    dependencies: Dict[str, List[DependencyInfo]] = field(default_factory=dict)
    frameworks: List[str] = field(default_factory=list)
    build_systems: List[str] = field(default_factory=list)
    detected_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def normalize_version(version: str) -> str:
    """
    Normalize version strings to a consistent format.
    
    Args:
        version: Raw version string
        
    Returns:
        Normalized version string
    """
    if not version:
        return "unspecified"
    
    # Remove leading/trailing whitespace
    version = version.strip()
    
    # Remove common version prefix characters
    prefix_chars = {'^', '~', '>', '<', '=', '~'}
    while version and version[0] in prefix_chars:
        version = version[1:].strip()
    
    # Handle version range operators with multiple characters
    if version.startswith(('>=', '<=', '==', '~=', '!=')):
        version = version[2:].strip()
    
    return version if version else "unspecified"


def parse_package_json(file_path: str) -> Tuple[List[DependencyInfo], List[str]]:
    """
    Parse package.json to extract dependencies.
    
    Args:
        file_path: Path to package.json file
        
    Returns:
        Tuple of (dependencies list, frameworks/build systems list)
    """
    dependencies: List[DependencyInfo] = []
    frameworks: List[str] = []
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = json.load(f)
        
        # Parse regular dependencies
        deps = content.get('dependencies', {})
        for name, version in deps.items():
            dependencies.append(DependencyInfo(
                name=name,
                version=normalize_version(version),
                dev=False,
                source_file='package.json'
            ))
        
        # Parse dev dependencies
        dev_deps = content.get('devDependencies', {})
        for name, version in dev_deps.items():
            dependencies.append(DependencyInfo(
                name=name,
                version=normalize_version(version),
                dev=True,
                source_file='package.json'
            ))
        
        # Parse peer dependencies
        peer_deps = content.get('peerDependencies', {})
        for name, version in peer_deps.items():
            dependencies.append(DependencyInfo(
                name=name,
                version=normalize_version(version),
                dev=False,
                source_file='package.json',
                metadata={'type': 'peer'}
            ))
        
        # Parse optional dependencies
        opt_deps = content.get('optionalDependencies', {})
        for name, version in opt_deps.items():
            dependencies.append(DependencyInfo(
                name=name,
                version=normalize_version(version),
                dev=False,
                source_file='package.json',
                metadata={'type': 'optional'}
            ))
        
        # Detect frameworks and build systems
        all_deps = set(deps.keys()) | set(dev_deps.keys())
        
        if 'react' in all_deps:
            frameworks.append('React')
        if 'react-dom' in all_deps:
            frameworks.append('React DOM')
        if 'angular' in all_deps or '@angular/core' in all_deps:
            frameworks.append('Angular')
        if 'vue' in all_deps:
            frameworks.append('Vue.js')
        if 'svelte' in all_deps:
            frameworks.append('Svelte')
        if 'next' in all_deps:
            frameworks.append('Next.js')
        if 'gatsby' in all_deps:
            frameworks.append('Gatsby')
        if 'nuxt' in all_deps:
            frameworks.append('Nuxt.js')
        if 'remix-run/react' in all_deps or '@remix-run/react' in all_deps:
            frameworks.append('Remix')
        if 'solid-js' in all_deps:
            frameworks.append('Solid.js')
        
        # Build tools
        build_tools = {
            'webpack': 'Webpack',
            'vite': 'Vite',
            'parcel': 'Parcel',
            'rollup': 'Rollup',
            'esbuild': 'esbuild',
            'babel': 'Babel',
            '@babel/core': 'Babel',
            'typescript': 'TypeScript',
            'ts-loader': 'TypeScript',
            'ts-node': 'TypeScript',
            '@types/node': 'TypeScript'
        }
        
        for tool, framework_name in build_tools.items():
            if tool in all_deps:
                frameworks.append(framework_name)
        
        # Testing frameworks
        test_frameworks = {
            'jest': 'Jest',
            'mocha': 'Mocha',
            'jasmine': 'Jasmine',
            'vitest': 'Vitest',
            '@testing-library/react': 'React Testing Library',
            '@testing-library/vue': 'Vue Testing Library',
            'cypress': 'Cypress',
            'playwright': 'Playwright',
            'selenium-webdriver': 'Selenium',
        }
        
        for tool, framework_name in test_frameworks.items():
            if tool in all_deps:
                frameworks.append(f'{framework_name} (Testing)')
        
    except json.JSONDecodeError as e:
        logger.warning(f"Error parsing package.json: Invalid JSON - {e}")
    except IOError as e:
        logger.warning(f"Error reading package.json: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error parsing package.json: {e}")
    
    return dependencies, frameworks


def parse_requirements_txt(file_path: str) -> Tuple[List[DependencyInfo], List[str]]:
    """
    Parse requirements.txt to extract dependencies.
    
    Args:
        file_path: Path to requirements.txt file
        
    Returns:
        Tuple of (dependencies list, frameworks/build systems list)
    """
    dependencies: List[DependencyInfo] = []
    frameworks: List[str] = []
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        for line in lines:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Skip file references (-r requirements.txt)
            if line.startswith('-r') or line.startswith('--require'):
                continue
            
            # Skip editable installs (-e .)
            if line.startswith('-e'):
                continue
            
            # Parse version specifier with regex
            # Matches patterns like: package, package==1.0.0, package>=1.0,<2.0, package~=1.0
            match = re.match(
                r'^([a-zA-Z0-9_-]+)(?:\s*([><=!~]{1,2}\s*[^;\s]+))?',
                line
            )
            if match:
                name = match.group(1).strip()
                version = match.group(2).strip() if match.group(2) else None
                
                # Handle version constraints
                if version:
                    version = normalize_version(version)
                
                # Extract any environment markers
                markers = None
                if ';' in line:
                    marker_match = re.search(r';\s*(.+)$', line)
                    if marker_match:
                        markers = marker_match.group(1).strip()
                
                dependency = DependencyInfo(
                    name=name,
                    version=version,
                    dev=False,
                    source_file='requirements.txt'
                )
                if markers:
                    dependency.metadata['markers'] = markers
                
                dependencies.append(dependency)
        
        # Detect common Python frameworks
        python_deps = [dep.name.lower() for dep in dependencies]
        
        framework_map = {
            'django': 'Django',
            'djangorestframework': 'Django REST Framework',
            'flask': 'Flask',
            'flask-restful': 'Flask-RESTful',
            'fastapi': 'FastAPI',
            'uvicorn': 'Uvicorn',
            'starlette': 'Starlette',
            'tornado': 'Tornado',
            'sqlalchemy': 'SQLAlchemy',
            'alembic': 'Alembic',
            'pytest': 'pytest (Testing)',
            'unittest': 'unittest (Testing)',
            'celery': 'Celery',
            'redis': 'Redis',
            'pymongo': 'PyMongo',
            'psycopg2': 'PostgreSQL',
            'pymysql': 'MySQL',
            'requests': 'Requests',
            'httpx': 'HTTPX',
            'aiohttp': 'aiohttp',
            'gunicorn': 'Gunicorn',
            'nginx': 'nginx',
        }
        
        for dep, framework in framework_map.items():
            if dep in python_deps:
                frameworks.append(framework)
        
        # Detect AI/ML frameworks
        ml_frameworks = {
            'tensorflow': 'TensorFlow',
            'keras': 'Keras',
            'torch': 'PyTorch',
            'torchvision': 'PyTorch Vision',
            'scikit-learn': 'scikit-learn',
            'numpy': 'NumPy',
            'pandas': 'Pandas',
            'matplotlib': 'Matplotlib',
            'seaborn': 'Seaborn',
        }
        
        for dep, framework in ml_frameworks.items():
            if dep in python_deps:
                frameworks.append(f'{framework} (Data/ML)')
        
    except IOError as e:
        logger.warning(f"Error reading requirements.txt: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error parsing requirements.txt: {e}")
    
    return dependencies, frameworks


def parse_cargo_toml(file_path: str) -> Tuple[List[DependencyInfo], List[str]]:
    """
    Parse Cargo.toml to extract dependencies.
    
    Args:
        file_path: Path to Cargo.toml file
        
    Returns:
        Tuple of (dependencies list, frameworks/build systems list)
    """
    dependencies: List[DependencyInfo] = []
    frameworks: List[str] = []
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # Track current section
        current_section: Optional[str] = None
        current_dependencies: Optional[str] = None
        
        for line_num, line in enumerate(content.split('\n'), 1):
            stripped = line.strip()
            
            # Skip comments
            if stripped.startswith('#'):
                continue
            
            # Detect section changes with regex
            section_match = re.match(r'^\[(.*?)\]$', stripped)
            if section_match:
                section = section_match.group(1).strip()
                current_section = section
                
                # Check if this is a dependencies section
                deps_match = re.match(r'^(dev-)?dependencies(?:\.(\w+))?$', section)
                if deps_match:
                    current_dependencies = deps_match.group(0)
                else:
                    current_dependencies = None
                continue
            
            # Skip if not in a dependencies section
            if current_dependencies is None:
                continue
            
            # Parse dependency line
            # Handle both simple "name = version" and table-style dependencies
            simple_dep_match = re.match(r'^(\w+)\s*=\s*["\']([^"\']+)["\']', line)
            if simple_dep_match:
                name = simple_dep_match.group(1)
                version = simple_dep_match.group(2)
                
                dependencies.append(DependencyInfo(
                    name=name,
                    version=normalize_version(version),
                    dev=current_dependencies.startswith('dev-'),
                    source_file='Cargo.toml',
                    metadata={'section': current_dependencies}
                ))
        
        if dependencies:
            frameworks.append('Rust Ecosystem')
            frameworks.append('Cargo')
            
        # Detect common Rust crates
        rust_deps = [dep.name.lower() for dep in dependencies]
        rust_frameworks = {
            'tokio': 'Tokio',
            'async-std': 'async-std',
            'actix-web': 'Actix Web',
            'rocket': 'Rocket',
            'warp': 'Warp',
            'axum': 'Axum',
            'serde': 'Serde',
            'nom': 'nom',
            'log': 'log',
            'env_logger': 'env_logger',
            'tracing': 'tracing',
            'anyhow': 'anyhow',
            'thiserror': 'thiserror',
            'clap': 'Clap',
        }
        
        for dep, framework in rust_frameworks.items():
            if dep in rust_deps:
                frameworks.append(framework)
        
    except IOError as e:
        logger.warning(f"Error reading Cargo.toml: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error parsing Cargo.toml: {e}")
    
    return dependencies, frameworks


def parse_go_mod(file_path: str) -> Tuple[List[DependencyInfo], List[str]]:
    """
    Parse go.mod to extract dependencies.
    
    Args:
        file_path: Path to go.mod file
        
    Returns:
        Tuple of (dependencies list, frameworks/build systems list)
    """
    dependencies: List[DependencyInfo] = []
    frameworks: List[str] = []
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        in_require = False
        in_indirect = False
        
        for line in content.split('\n'):
            stripped = line.strip()
            
            # Skip comments
            if stripped.startswith('//'):
                continue
            
            # Handle require blocks
            if stripped.startswith('require'):
                # Check if single-line require
                if stripped.endswith(')') or ')' in stripped:
                    # Single line require
                    match = re.match(r'require\s+(\S+)\s+(\S+)', stripped)
                    if match and not match.group(1) == '(':
                        name = match.group(1)
                        version = match.group(2).rstrip(')')
                        dependencies.append(DependencyInfo(
                            name=name,
                            version=normalize_version(version),
                            dev=False,
                            source_file='go.mod',
                            metadata={'type': 'direct'}
                        ))
                else:
                    in_require = True
                
                continue
            
            # End of require block
            if stripped.endswith(')') and in_require:
                in_require = False
                in_indirect = False
                continue
            
            # Check for indirect marker
            if in_require and 'indirect' in stripped:
                in_indirect = True
                continue
            
            # Parse dependency line in require block
            if in_require and not in_indirect:
                match = re.match(r'(\S+)\s+(\S+)', stripped)
                if match:
                    name = match.group(1)
                    version = match.group(2)
                    
                    dep_type = 'direct'
                    if '//' in name:
                        name = name.split('//')[0].strip()
                    
                    dependencies.append(DependencyInfo(
                        name=name,
                        version=normalize_version(version),
                        dev=False,
                        source_file='go.mod',
                        metadata={'type': dep_type}
                    ))
            
            # Handle exclude blocks
            if stripped.startswith('exclude'):
                in_require = False
            
            # Handle replace blocks
            if stripped.startswith('replace'):
                in_require = False
        
        if dependencies:
            frameworks.append('Go Ecosystem')
            frameworks.append('Go Modules')
            
        # Detect common Go packages
        go_deps = [dep.name.lower() for dep in dependencies]
        go_frameworks = {
            'github.com/gin-gonic/gin': 'Gin',
            'github.com/gorilla/mux': 'Gorilla Mux',
            'github.com/labstack/echo': 'Echo',
            'github.com/go-chi/chi': 'Chi',
            'github.com/rs/zerolog': 'Zerolog',
            'go.uber.org/zap': 'Zap',
            'github.com/sirupsen/logrus': 'Logrus',
            'gorm.io/gorm': 'GORM',
            'github.com/lib/pq': 'PostgreSQL',
            'github.com/go-sql-driver/mysql': 'MySQL',
            'github.com/stretchr/testify': 'Testify',
        }
        
        for dep, framework in go_frameworks.items():
            if dep in go_deps:
                frameworks.append(framework)
        
    except IOError as e:
        logger.warning(f"Error reading go.mod: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error parsing go.mod: {e}")
    
    return dependencies, frameworks


def parse_pyproject_toml(file_path: str) -> Tuple[List[DependencyInfo], List[str]]:
    """
    Parse pyproject.toml to extract dependencies.
    
    Args:
        file_path: Path to pyproject.toml file
        
    Returns:
        Tuple of (dependencies list, frameworks/build systems list)
    """
    dependencies: List[DependencyInfo] = []
    frameworks: List[str] = []
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # Simple TOML parsing without external libraries
        current_section: Optional[str] = None
        in_array = False
        array_content = []
        
        for line in content.split('\n'):
            stripped = line.strip()
            
            # Skip comments
            if stripped.startswith('#'):
                continue
            
            # Section detection
            section_match = re.match(r'^\[([^\]]+)\]$', stripped)
            if section_match:
                # Process any pending array content
                if in_array and array_content:
                    process_dependencies_array(
                        array_content, dependencies, current_section, file_path
                    )
                    array_content = []
                    in_array = False
                
                current_section = section_match.group(1).strip()
                continue
            
            # Check for array start
            if 'dependencies' in stripped and '=' in stripped:
                if stripped.endswith('['):
                    in_array = True
                    continue
                elif '[' in stripped:
                    # Single-line array
                    array_content.append(stripped)
                    in_array = True
                    continue
            
            # Collect array content
            if in_array:
                if ']' in stripped:
                    # End of array
                    if stripped != ']':
                        array_content.append(stripped)
                    process_dependencies_array(
                        array_content, dependencies, current_section, file_path
                    )
                    array_content = []
                    in_array = False
                else:
                    array_content.append(stripped)
        
        # Process any remaining array content
        if in_array and array_content:
            process_dependencies_array(
                array_content, dependencies, current_section, file_path
            )
        
        if dependencies:
            frameworks.append('Python (pyproject.toml)')
            
        # Detect frameworks
        py_deps = [dep.name.lower() for dep in dependencies]
        framework_map = {
            'django': 'Django',
            'djangorestframework': 'Django REST Framework',
            'flask': 'Flask',
            'fastapi': 'FastAPI',
            'pytest': 'pytest',
            'poetry-core': 'Poetry',
        }
        
        for dep, framework in framework_map.items():
            if dep in py_deps:
                frameworks.append(framework)
        
    except IOError as e:
        logger.warning(f"Error reading pyproject.toml: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error parsing pyproject.toml: {e}")
    
    return dependencies, frameworks


def process_dependencies_array(
    array_content: List[str],
    dependencies: List[DependencyInfo],
    section: Optional[str],
    source_file: str
) -> None:
    """
    Process dependency array content and add to dependencies list.
    
    Args:
        array_content: List of lines containing dependency definitions
        dependencies: List to append parsed dependencies to
        section: Current TOML section
        source_file: Source file name
    """
    # Join and normalize content
    content = ' '.join(array_content).strip()
    content = content.rstrip(']').rstrip(',')
    
    # Split by commas and process each dependency
    for dep_str in content.split(','):
        dep_str = dep_str.strip()
        if not dep_str:
            continue
        # Remove quotes
        dep_str = dep_str.strip('"').strip("'")
        
        # Parse name and version
        match = re.match(r'^([^>=<~!]+)([>=<~!]+[^,]*)?$', dep_str)
        if match:
            name = match.group(1).strip()
            version = match.group(2).strip() if match.group(2) else None
            
            dependencies.append(DependencyInfo(
                name=name,
                version=normalize_version(version) if version else None,
                dev='dev' in section or 'optional' in section,
                source_file=source_file,
                metadata={'section': section}
            ))


def analyze_directory(directory: str, verbose: bool = False, depth: int = 10) -> ProjectAnalysis:
    """
    Analyze a project directory to detect tech stack.
    
    Args:
        directory: Path to the project directory
        verbose: Whether to print verbose information
        depth: Maximum directory depth to scan
        
    Returns:
        ProjectAnalysis object containing analysis results
    """
    analysis = ProjectAnalysis(directory=directory)
    dir_path = Path(directory).resolve()
    
    # Validate directory
    if not dir_path.exists():
        analysis.errors.append(f"Directory does not exist: {directory}")
        return analysis
    
    if not dir_path.is_dir():
        analysis.errors.append(f"Path is not a directory: {directory}")
        return analysis
    
    if verbose:
        print(f"Scanning directory: {dir_path}")
    
    # Step 1: Scan for manifest files and parse dependencies
    manifest_parsers = {
        'package.json': parse_package_json,
        'requirements.txt': parse_requirements_txt,
        'Cargo.toml': parse_cargo_toml,
        'go.mod': parse_go_mod,
        'pyproject.toml': parse_pyproject_toml,
    }
    
    for manifest_file, parser in manifest_parsers.items():
        manifest_path = dir_path / manifest_file
        if manifest_path.exists():
            analysis.detected_files.append(manifest_file)
            if verbose:
                print(f"  Found {manifest_file}")
            
            deps, frameworks = parser(str(manifest_path))
            for dep in deps:
                if manifest_file not in analysis.dependencies:
                    analysis.dependencies[manifest_file] = []
                analysis.dependencies[manifest_file].append(dep)
            
            analysis.frameworks.extend(frameworks)
    
    # Step 2: Analyze file extensions to determine language
    extension_counts: Dict[str, int] = {}
    total_files = 0
    
    try:
        for root, dirs, files in os.walk(dir_path):
            # Calculate depth relative to root
            current_depth = len(Path(root).relative_to(dir_path).parts)
            if current_depth > depth:
                # Skip deeper directories
                dirs[:] = []
                continue
            
            # Modify dirs in-place to skip certain directories
            dirs[:] = [d for d in dirs if d not in SKIP_DIRECTORIES and not d.startswith('.')]
            
            for file in files:
                file_path = Path(file)
                
                # Skip hidden files and files in skip set
                if file.startswith('.') or file.lower() in SKIP_FILES:
                    continue
                
                # Get file extension
                file_ext = file_path.suffix.lower().lstrip('.')
                
                # Skip files without recognized extensions
                if file_ext not in LANGUAGE_EXTENSIONS:
                    continue
                
                # Count language occurrences
                language = LANGUAGE_EXTENSIONS[file_ext]
                extension_counts[language] = extension_counts.get(language, 0) + 1
                total_files += 1
    
    except PermissionError as e:
        analysis.errors.append(f"Permission denied while scanning: {e}")
    except Exception as e:
        analysis.errors.append(f"Error while scanning directory: {e}")
    
    # Calculate language percentages
    if total_files > 0:
        for language, count in extension_counts.items():
            percentage = (count / total_files) * 100
            analysis.language_percentages[language] = round(percentage, 2)
        
        # Determine primary language (highest percentage)
        if extension_counts:
            primary_language = max(extension_counts.items(), key=lambda x: x[1])[0]
            analysis.primary_language = primary_language
    else:
        analysis.warnings.append("No source files detected for language analysis")
    
    # Clean up frameworks list (remove duplicates)
    analysis.frameworks = list(set(analysis.frameworks))
    
    # Detect build systems
    build_system_map = {
        'package.json': 'npm/yarn/pnpm',
        'requirements.txt': 'pip',
        'pyproject.toml': 'Poetry/pip',
        'Cargo.toml': 'Cargo',
        'go.mod': 'Go Modules',
        'pom.xml': 'Maven',
        'build.gradle': 'Gradle',
        'composer.json': 'Composer',
        'Gemfile': 'Bundler',
    }
    
    for manifest_file, build_system in build_system_map.items():
        if manifest_file in analysis.detected_files:
            analysis.build_systems.append(build_system)
    
    # Add additional warnings
    if not analysis.detected_files:
        analysis.warnings.append("No package manifest files detected")
    
    return analysis


def generate_system_prompt(analysis: ProjectAnalysis) -> str:
    """
    Generate a formatted system prompt based on project analysis.
    
    Args:
        analysis: ProjectAnalysis object containing analysis results
        
    Returns:
        Formatted system prompt in Markdown format
    """
    prompt_parts = []
    
    # Header with timestamp
    from datetime import datetime
    timestamp = datetime.now().isoformat()
    
    prompt_parts.append(f"# System Prompt for Code Analysis")
    prompt_parts.append(f"_Generated at: {timestamp}_")
    prompt_parts.append("")
    prompt_parts.append("You are analyzing code for a project with the following technology stack:")
    prompt_parts.append("")
    
    # Project Overview
    prompt_parts.append("## Project Overview")
    prompt_parts.append(f"- **Directory**: `{analysis.directory}`")
    
    if analysis.primary_language:
        prompt_parts.append(f"- **Primary Language**: {analysis.primary_language}")
    
    prompt_parts.append("")
    
    # Primary Language Section
    if analysis.primary_language:
        prompt_parts.append("## Primary Language")
        prompt_parts.append(f"This project is primarily built using **{analysis.primary_language}**. ")
        prompt_parts.append("All code analysis, suggestions, and examples should follow ")
        prompt_parts.append(f"the conventions and best practices for {analysis.primary_language}.")
        prompt_parts.append("")
    
    # Language Distribution
    if analysis.language_percentages:
        prompt_parts.append("## Language Distribution")
        prompt_parts.append("Based on file extensions detected in the codebase:")
        prompt_parts.append("")
        
        # Sort by percentage descending
        sorted_languages = sorted(
            analysis.language_percentages.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        for language, percentage in sorted_languages:
            bar_length = int(percentage // 5)
            bar = '█' * bar_length
            prompt_parts.append(f"- {language:20s} {percentage:5.1f}% {bar}")
        
        prompt_parts.append("")
    
    # Frameworks and Libraries
    if analysis.frameworks:
        prompt_parts.append("## Frameworks and Libraries")
        prompt_parts.append("The following frameworks and libraries are used in this project:")
        prompt_parts.append("")
        
        for framework in sorted(analysis.frameworks):
            prompt_parts.append(f"- **{framework}**")
        
        prompt_parts.append("")
    
    # Build Systems
    if analysis.build_systems:
        prompt_parts.append("## Build Systems and Package Managers")
        prompt_parts.append("Package management and build tools detected:")
        prompt_parts.append("")
        
        for system in sorted(analysis.build_systems):
            prompt_parts.append(f"- {system}")
        
        prompt_parts.append("")
    
    # Dependencies
    if analysis.dependencies:
        prompt_parts.append("## Dependencies and Versions")
        prompt_parts.append("The project uses the following dependencies:")
        prompt_parts.append("")
        
        for manifest_file in sorted(analysis.dependencies.keys()):
            deps = analysis.dependencies[manifest_file]
            if not deps:
                continue
            
            prompt_parts.append(f"### {manifest_file}")
            prompt_parts.append("")
            
            # Separate dev dependencies
            prod_deps = [d for d in deps if not d.dev]
            dev_deps = [d for d in deps if d.dev]
            
            if prod_deps:
                for dep in sorted(prod_deps, key=lambda x: x.name.lower()):
                    version_str = f" (v{dep.version})" if dep.version else ""
                    metadata_str = ""
                    if dep.metadata:
                        metadata_parts = [f"{k}={v}" for k, v in dep.metadata.items()]
                        if metadata_parts:
                            metadata_str = f" [{', '.join(metadata_parts)}]"
                    prompt_parts.append(f"- {dep.name}{version_str}{metadata_str}")
                prompt_parts.append("")
            
            if dev_deps:
                prompt_parts.append("**Development Dependencies:**")
                prompt_parts.append("")
                for dep in sorted(dev_deps, key=lambda x: x.name.lower()):
                    version_str = f" (v{dep.version})" if dep.version else ""
                    metadata_str = ""
                    if dep.metadata:
                        metadata_parts = [f"{k}={v}" for k, v in dep.metadata.items()]
                        if metadata_parts:
                            metadata_str = f" [{', '.join(metadata_parts)}]"
                    prompt_parts.append(f"- {dep.name}{version_str}{metadata_str}")
                prompt_parts.append("")
    
    # Code Analysis Instructions
    prompt_parts.append("## Code Analysis Instructions")
    prompt_parts.append("")
    prompt_parts.append("When working with this codebase, please adhere to the following guidelines:")
    prompt_parts.append("")
    prompt_parts.append("### Language and Conventions")
    prompt_parts.append("1. Follow the coding conventions and style patterns used in the existing codebase")
    prompt_parts.append("2. Use appropriate data structures and idiomatic patterns for the primary language")
    prompt_parts.append("3. Respect naming conventions (camelCase, snake_case, etc.) used throughout the project")
    prompt_parts.append("")
    
    prompt_parts.append("### Framework Usage")
    prompt_parts.append("1. Utilize the detected frameworks according to their official best practices")
    prompt_parts.append("2. Follow initialization and configuration patterns established in the codebase")
    prompt_parts.append("3. Consider framework-specific performance optimizations")
    prompt_parts.append("")
    
    prompt_parts.append("### Dependency Management")
    prompt_parts.append("1. When suggesting new dependencies, prefer versions compatible with existing ones")
    prompt_parts.append("2. Consider alternative libraries already available in the project")
    prompt_parts.append("3. Provide installation commands appropriate for the detected build systems")
    prompt_parts.append("")
    
    prompt_parts.append("### Build and Integration")
    prompt_parts.append("1. Ensure suggestions integrate correctly with the project's build system")
    prompt_parts.append("2. Provide configuration changes in the format expected by the build tools")
    prompt_parts.append("3. Consider build-time and runtime dependencies separately")
    prompt_parts.append("")
    
    prompt_parts.append("### Code Quality")
    prompt_parts.append("1. Write code that matches the existing code structure and organization")
    prompt_parts.append("2. Provide proper error handling consistent with the codebase")
    prompt_parts.append("3. Include appropriate testing approaches based on detected test frameworks")
    prompt_parts.append("4. Add documentation in the same style as existing code comments")
    prompt_parts.append("")
    
    # Analysis Notes
    if analysis.errors or analysis.warnings:
        prompt_parts.append("---")
        prompt_parts.append("")
        prompt_parts.append("## Analysis Notes")
        
        if analysis.warnings:
            prompt_parts.append("**Warnings:**")
            for warning in analysis.warnings:
                prompt_parts.append(f"- {warning}")
            prompt_parts.append("")
        
        if analysis.errors:
            prompt_parts.append("**Errors encountered during analysis:**")
            for error in analysis.errors:
                prompt_parts.append(f"- {error}")
            prompt_parts.append("")
        
        prompt_parts.append("Note: These issues may affect the completeness of the analysis.")
        prompt_parts.append("Please examine the codebase directly for any missing information.")
    
    return "\n".join(prompt_parts)


def write_output(content: str, output_path: Optional[str] = None) -> bool:
    """
    Write content to stdout or a file.
    
    Args:
        content: The content to write
        output_path: Optional file path, uses stdout if None
        
    Returns:
        True if successful, False otherwise
    """
    try:
        if output_path:
            # Ensure output directory exists
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            file_size = output_file.stat().st_size
            print(f"✓ System prompt written to: {output_path} ({file_size} bytes)", file=sys.stderr)
        else:
            print(content)
        return True
    except IOError as e:
        print(f"✗ Error writing output: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"✗ Unexpected error writing output: {e}", file=sys.stderr)
        return False


def validate_directory(directory: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that the specified directory exists and is accessible.
    
    Args:
        directory: Path to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        dir_path = Path(directory).resolve()
        
        if not dir_path.exists():
            return False, f"Directory does not exist: {directory}"
        
        if not dir_path.is_dir():
            return False, f"Path is not a directory: {directory}"
        
        if not os.access(dir_path, os.R_OK):
            return False, f"Directory is not readable: {directory}"
        
        return True, None
    except Exception as e:
        return False, f"Error validating directory: {e}"


def setup_argparser() -> argparse.ArgumentParser:
    """
    Set up and return the argument parser.
    
    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        description=(
            'Generate a system prompt based on codebase analysis. '
            'This tool scans project manifests and source files to create '
            'a comprehensive system prompt for LLM assistance.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan current directory and print to stdout
  %(prog)s
  
  # Scan a specific directory and save to file
  %(prog)s -d /path/to/project -o SYSTEM_PROMPT.md
  
  # Display verbose output while scanning
  %(prog)s -d . -o system_prompt.txt -v
  
  # Limit scan depth for large projects
  %(prog)s -d ~/large-project --depth 5
  
  # Enable debug logging
  %(prog)s --debug
        """
    )
    
    parser.add_argument(
        '-d', '--directory',
        default='.',
        metavar='DIR',
        help='Directory to scan (default: current directory)'
    )
    
    parser.add_argument(
        '-o', '--output',
        metavar='FILE',
        help=(
            'Output file path for the generated system prompt. '
            'If not specified, prints to stdout.'
        )
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output during scanning'
    )
    
    parser.add_argument(
        '--depth',
        type=int,
        default=10,
        metavar='N',
        help='Maximum directory depth to scan (default: 10)'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s 1.0.0'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging for troubleshooting'
    )
    
    return parser


def get_api_config() -> Dict[str, Optional[str]]:
    """
    Load API configuration from environment variables.
    
    Returns:
        Dictionary with API configuration values
    """
    config = {
        'OPENAI_API_KEY': os.environ.get('OPENAI_API_KEY'),
        'ANTHROPIC_API_KEY': os.environ.get('ANTHROPIC_API_KEY'),
        'DS4_API_KEY': os.environ.get('DS4_API_KEY'),
    }
    return config


def main() -> int:
    """
    Main function to coordinate the CLI tool.
    
    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    parser = setup_argparser()
    args = parser.parse_args()
    
    # Set debug logging if requested
    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    # Get API configuration (graceful degradation)
    api_config = get_api_config()
    if args.debug:
        configured_apis = [k for k, v in api_config.items() if v]
        logger.debug(f"Configured APIs: {configured_apis}")
    
    # Validate directory
    is_valid, error_msg = validate_directory(args.directory)
    if not is_valid:
        print(f"Error: {error_msg}", file=sys.stderr)
        return 1
    
    # Analyze the directory
    if args.verbose:
        print(f"Starting analysis of: {args.directory}")
    
    analysis = analyze_directory(
        args.directory,
        verbose=args.verbose,
        depth=args.depth
    )
    
    # Log any analysis warnings
    if analysis.warnings and args.verbose:
        for warning in analysis.warnings:
            logger.warning(warning)
    
    # Log any analysis errors
    if analysis.errors:
        for error in analysis.errors:
            logger.error(error)
    
    # Generate the system prompt
    try:
        system_prompt = generate_system_prompt(analysis)
    except Exception as e:
        print(f"Error generating system prompt: {e}", file=sys.stderr)
        return 1
    
    # Output the result
    if not write_output(system_prompt, args.output):
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())