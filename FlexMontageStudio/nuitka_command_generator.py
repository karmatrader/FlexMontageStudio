import os
import ast
import re
import sys
import platform
from collections import defaultdict, Counter
from pathlib import Path
import json
import argparse
from typing import Set, List, Dict, Optional, Tuple

# Опциональные импорты
try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import toml

    HAS_TOML = True
except ImportError:
    HAS_TOML = False


class NuitkaCommandGenerator:
    def __init__(self, project_path: str, main_script: str):
        self.project_path = Path(project_path).resolve()
        self.main_script = main_script
        self.imports = defaultdict(list)
        self.import_counts = Counter()
        self.external_packages = set()
        self.standard_library = set()
        self.local_imports = set()
        self.data_files = []
        self.data_dirs = []
        self.plugin_modules = set()
        self.included_packages = set()
        self.excluded_modules = set()
        self.python_files = []

    def is_standard_library(self, module_name: str) -> bool:
        """Проверяет, является ли модуль частью стандартной библиотеки Python"""
        import importlib.util

        stdlib_modules = {
            'os', 'sys', 'json', 'csv', 'xml', 'urllib', 'http', 'email',
            'datetime', 'time', 'calendar', 'collections', 'itertools',
            'functools', 'operator', 're', 'string', 'textwrap', 'unicodedata',
            'math', 'random', 'statistics', 'pathlib', 'glob', 'fnmatch',
            'tempfile', 'shutil', 'pickle', 'sqlite3', 'threading', 'multiprocessing',
            'subprocess', 'socket', 'ssl', 'asyncio', 'logging', 'unittest',
            'argparse', 'configparser', 'io', 'gzip', 'zipfile', 'tarfile',
            'tkinter', 'turtle', 'tkinter.ttk', 'abc', 'base64', 'binascii',
            'bisect', 'builtins', 'codecs', 'copy', 'copyreg', 'decimal',
            'enum', 'fractions', 'heapq', 'hmac', 'html', 'keyword', 'locale',
            'mimetypes', 'numbers', 'platform', 'pprint', 'queue', 'secrets',
            'traceback', 'types', 'typing', 'uuid', 'warnings', 'weakref'
        }

        root_module = module_name.split('.')[0]

        if root_module in stdlib_modules:
            return True

        try:
            spec = importlib.util.find_spec(root_module)
            if spec and spec.origin:
                origin = str(spec.origin)
                return ('site-packages' not in origin and
                        ('/usr/lib/python' in origin or
                         '/usr/local/lib/python' in origin or
                         'python3.' in origin and '/lib/' in origin))
        except (ImportError, ModuleNotFoundError):
            pass

        return False

    def extract_imports_from_file(self, file_path: Path) -> List[Dict]:
        """Извлекает импорты из Python файла"""
        imports = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append({
                            'type': 'import',
                            'module': alias.name,
                            'alias': alias.asname,
                            'line': node.lineno
                        })

                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    for alias in node.names:
                        imports.append({
                            'type': 'from',
                            'module': module,
                            'name': alias.name,
                            'alias': alias.asname,
                            'line': node.lineno,
                            'level': node.level
                        })

        except (SyntaxError, UnicodeDecodeError) as e:
            print(f"⚠️  Ошибка при обработке файла {file_path}: {e}")

        return imports

    def analyze_project(self):
        """Анализирует весь проект"""
        print("🔍 Анализируем Python файлы...")

        # Анализ Python файлов
        python_files = list(self.project_path.rglob("*.py"))
        excluded_dirs = {'venv', 'env', '.venv', '__pycache__', '.git', 'node_modules', 'build', 'dist'}

        for file_path in python_files:
            if any(part in file_path.parts for part in excluded_dirs):
                continue

            self.python_files.append(file_path)
            imports = self.extract_imports_from_file(file_path)

            for imp in imports:
                if imp['type'] == 'import':
                    module = imp['module']
                elif imp['type'] == 'from':
                    module = imp['module'] if imp['module'] else imp['name']

                if not module:
                    continue

                self.import_counts[module] += 1

                # Классификация импортов
                if imp.get('level', 0) > 0:  # Относительные импорты
                    self.local_imports.add(module)
                elif self.is_standard_library(module):
                    self.standard_library.add(module)
                elif module.startswith('.'):
                    self.local_imports.add(module)
                else:
                    self.external_packages.add(module)

        print("🔍 Анализируем конфигурационные файлы...")
        self._analyze_config_files()

        print("🔍 Ищем файлы данных...")
        self._find_data_files()

        print("🔍 Определяем плагины Nuitka...")
        self._determine_nuitka_plugins()

        print("🔍 Анализируем зависимости пакетов...")
        self._analyze_package_dependencies()

        print(f"✅ Найдено {len(self.external_packages)} внешних пакетов")
        print(f"✅ Найдено {len(self.data_files)} файлов данных")
        print(f"✅ Найдено {len(self.data_dirs)} папок с данными")
        print(f"✅ Определено {len(self.plugin_modules)} плагинов")

        # Показываем информацию о Qt если есть
        qt_frameworks = [pkg for pkg in self.external_packages
                         if pkg.split('.')[0].lower() in ['pyqt5', 'pyside2', 'pyqt6', 'pyside6']]
        if qt_frameworks:
            print(f"🎨 Qt фреймворки: {', '.join(qt_frameworks)}")

        # Предупреждения
        if len([pkg for pkg in self.external_packages
                if pkg.split('.')[0].lower() in ['pyqt5', 'pyside2', 'pyqt6', 'pyside6']]) > 1:
            print("⚠️  Обнаружено несколько Qt фреймворков - будет выбран один для избежания конфликтов")

    def _analyze_config_files(self):
        """Анализирует конфигурационные файлы для поиска зависимостей"""
        config_patterns = [
            "requirements*.txt", "Pipfile", "Pipfile.lock",
            "pyproject.toml", "setup.py", "setup.cfg",
            "environment.yml", "conda.yml"
        ]

        for pattern in config_patterns:
            for file_path in self.project_path.rglob(pattern):
                if any(part in file_path.parts for part in {'venv', 'env', '__pycache__', '.git'}):
                    continue

                dependencies = self._extract_config_dependencies(file_path)
                for dep in dependencies:
                    if not self.is_standard_library(dep) and dep:
                        self.external_packages.add(dep)

    def _extract_config_dependencies(self, file_path: Path) -> Set[str]:
        """Извлекает зависимости из конфигурационных файлов"""
        dependencies = set()

        try:
            if 'requirements' in file_path.name and file_path.suffix == '.txt':
                dependencies = self._parse_requirements_txt(file_path)
            elif file_path.name == 'Pipfile':
                dependencies = self._parse_pipfile(file_path)
            elif file_path.name == 'Pipfile.lock':
                dependencies = self._parse_pipfile_lock(file_path)
            elif file_path.name == 'pyproject.toml' and HAS_TOML:
                dependencies = self._parse_pyproject_toml(file_path)
            elif file_path.name in ['environment.yml', 'conda.yml'] and HAS_YAML:
                dependencies = self._parse_conda_env(file_path)
        except Exception as e:
            print(f"⚠️  Ошибка при анализе {file_path}: {e}")

        return dependencies

    def _parse_requirements_txt(self, file_path: Path) -> Set[str]:
        """Парсит requirements.txt"""
        dependencies = set()

        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('-'):
                    if line.startswith('-r '):
                        continue
                    pkg_name = re.split(r'[>=<!\[\]@#]', line)[0].strip()
                    if pkg_name:
                        dependencies.add(pkg_name)

        return dependencies

    def _parse_pipfile(self, file_path: Path) -> Set[str]:
        """Парсит Pipfile"""
        dependencies = set()

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        in_packages = False
        in_dev_packages = False

        for line in content.splitlines():
            line = line.strip()
            if line == '[packages]':
                in_packages = True
                in_dev_packages = False
                continue
            elif line == '[dev-packages]':
                in_packages = False
                in_dev_packages = True
                continue
            elif line.startswith('['):
                in_packages = False
                in_dev_packages = False
                continue

            if (in_packages or in_dev_packages) and '=' in line:
                pkg_name = line.split('=')[0].strip().strip('"\'')
                if pkg_name:
                    dependencies.add(pkg_name)

        return dependencies

    def _parse_pipfile_lock(self, file_path: Path) -> Set[str]:
        """Парсит Pipfile.lock"""
        dependencies = set()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for section in ['default', 'develop']:
                if section in data:
                    dependencies.update(data[section].keys())
        except json.JSONDecodeError:
            pass

        return dependencies

    def _parse_pyproject_toml(self, file_path: Path) -> Set[str]:
        """Парсит pyproject.toml"""
        dependencies = set()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = toml.load(f)

            # Poetry зависимости
            if 'tool' in data and 'poetry' in data['tool']:
                poetry_data = data['tool']['poetry']
                for key in ['dependencies', 'dev-dependencies']:
                    if key in poetry_data:
                        deps = poetry_data[key]
                        if isinstance(deps, dict):
                            dependencies.update(deps.keys())

            # setuptools зависимости
            if 'project' in data and 'dependencies' in data['project']:
                for dep in data['project']['dependencies']:
                    pkg_name = re.split(r'[=:<>!\[\]@]', dep)[0].strip()
                    dependencies.add(pkg_name)

        except toml.TomlDecodeError:
            pass

        return dependencies

    def _parse_conda_env(self, file_path: Path) -> Set[str]:
        """Парсит environment.yml conda файлы"""
        dependencies = set()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if data and 'dependencies' in data:
                for dep in data['dependencies']:
                    if isinstance(dep, str):
                        pkg_name = re.split(r'[=:<>]', dep)[0].strip()
                        dependencies.add(pkg_name)
                    elif isinstance(dep, dict) and 'pip' in dep:
                        for pip_dep in dep['pip']:
                            pkg_name = re.split(r'[=:<>]', pip_dep)[0].strip()
                            dependencies.add(pkg_name)

        except yaml.YAMLError:
            pass

        return dependencies

    def _find_data_files(self):
        """Находит файлы и папки данных"""
        # Паттерны для отдельных файлов данных
        data_file_patterns = [
            "*.json", "*.yaml", "*.yml", "*.toml", "*.ini", "*.cfg", "*.conf",
            "*.txt", "*.csv", "*.xml", "*.html", "*.css", "*.js",
            "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.svg", "*.bmp",
            "*.ttf", "*.otf", "*.woff", "*.woff2",
            "*.sql", "*.db", "*.sqlite", "*.sqlite3",
            "*.pdf", "*.doc", "*.docx", "*.md"
        ]

        # Папки, которые обычно содержат данные
        data_dir_names = {
            'templates', 'static', 'assets', 'data', 'config', 'resources',
            'images', 'icons', 'fonts', 'styles', 'css', 'js', 'media',
            'locale', 'locales', 'translations', 'i18n', 'docs'
        }

        excluded_dirs = {'venv', 'env', '.venv', '__pycache__', '.git', 'node_modules', 'build', 'dist'}

        # Поиск файлов данных
        for pattern in data_file_patterns:
            for file_path in self.project_path.rglob(pattern):
                if any(part in file_path.parts for part in excluded_dirs):
                    continue

                rel_path = file_path.relative_to(self.project_path)
                self.data_files.append(rel_path)

        # Поиск папок с данными
        for dir_path in self.project_path.rglob("*"):
            if (dir_path.is_dir() and
                    dir_path.name.lower() in data_dir_names and
                    not any(part in dir_path.parts for part in excluded_dirs)):
                rel_path = dir_path.relative_to(self.project_path)
                self.data_dirs.append(rel_path)

    def _get_available_nuitka_plugins(self):
        """Получает список доступных плагинов Nuitka"""
        try:
            import subprocess
            result = subprocess.run(['python', '-m', 'nuitka', '--plugin-list'],
                                    capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                # Парсим вывод плагинов
                plugins = set()
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line and not line.startswith('Available') and not line.startswith('='):
                        # Извлекаем имя плагина (обычно первое слово)
                        plugin_name = line.split()[0] if line.split() else ''
                        if plugin_name and not plugin_name.startswith('-'):
                            plugins.add(plugin_name)
                return plugins
        except Exception as e:
            print(f"⚠️  Не удалось получить список плагинов: {e}")
        return set()

    def _validate_plugins(self):
        """Проверяет доступность плагинов и удаляет недоступные"""
        available_plugins = self._get_available_nuitka_plugins()

        if available_plugins:
            # Фильтруем только доступные плагины
            valid_plugins = set()
            for plugin in self.plugin_modules:
                if plugin in available_plugins:
                    valid_plugins.add(plugin)
                else:
                    print(f"⚠️  Плагин '{plugin}' недоступен, пропускаем")

            self.plugin_modules = valid_plugins
        else:
            print("⚠️  Не удалось проверить доступные плагины, используем все")

    def _determine_nuitka_plugins(self):
        """Определяет необходимые плагины Nuitka"""
        # Проверяем версию Nuitka для совместимости
        nuitka_version = self._get_nuitka_version()

        plugin_map = {
            'tkinter': 'tk-inter',
            'numpy': 'numpy',
            'scipy': 'numpy',  # scipy использует numpy плагин
            'matplotlib': 'matplotlib',
            'kivy': 'kivy',
            'pygame': 'pygame',
            'multiprocessing': 'multiprocessing',
            'gevent': 'gevent',
            'twisted': 'twisted',
            'trio': 'trio',
            'dill': 'dill-compat',
            'eventlet': 'eventlet',
            'pmw': 'pmw-freezer',
            'torch': 'torch',
            'tensorflow': 'tensorflow',
            'sklearn': 'sklearn',
            'transformers': 'transformers',
        }

        # Сначала определяем какие Qt фреймворки используются (без дубликатов)
        qt_frameworks = set()
        qt_usage_count = {}

        for package in self.external_packages:
            package_name = package.split('.')[0].lower()
            if package_name in ['pyqt5', 'pyside2', 'pyqt6', 'pyside6']:
                qt_frameworks.add(package_name)
                # Суммируем использование всех модулей этого фреймворка
                if package_name not in qt_usage_count:
                    qt_usage_count[package_name] = 0
                qt_usage_count[package_name] += self.import_counts.get(package, 0)

        # Добавляем обычные плагины (не Qt)
        for package in self.external_packages:
            package_name = package.split('.')[0].lower()
            if package_name in plugin_map:
                self.plugin_modules.add(plugin_map[package_name])

        # Обрабатываем Qt плагины с разрешением конфликтов
        self._resolve_qt_conflicts(list(qt_frameworks), qt_usage_count)

        # Проверяем доступность плагинов
        self._validate_plugins()

    def _resolve_qt_conflicts(self, qt_frameworks, qt_usage_count):
        """Разрешает конфликты между Qt фреймворками"""
        if not qt_frameworks:
            return

        # Убираем дубликаты из списка
        qt_frameworks = list(set(qt_frameworks))

        if len(qt_frameworks) == 1:
            # Только один фреймворк - добавляем его плагин
            self.plugin_modules.add(qt_frameworks[0])
            print(f"📦 Найден Qt фреймворк: {qt_frameworks[0]}")
            return

        # Несколько Qt фреймворков - выбираем наиболее используемый
        print(f"⚠️  Обнаружено несколько Qt фреймворков: {', '.join(sorted(set(qt_frameworks)))}")

        # Подсчитываем реальное использование через анализ импортов
        real_usage = self._count_qt_usage_in_code()

        if real_usage:
            # Используем данные из анализа кода
            most_used = max(real_usage.items(), key=lambda x: x[1])
            chosen_framework = most_used[0]
            print(f"🎯 Выбираем наиболее используемый в коде: {chosen_framework} ({most_used[1]} импортов)")
        elif qt_usage_count:
            # Фильтруем дубликаты и считаем правильно
            filtered_usage = {}
            for fw in set(qt_frameworks):
                count = 0
                for package in self.external_packages:
                    if package.split('.')[0].lower() == fw:
                        count += self.import_counts.get(package, 0)
                filtered_usage[fw] = count

            if filtered_usage:
                most_used = max(filtered_usage.items(), key=lambda x: x[1])
                chosen_framework = most_used[0]
                print(f"🎯 Выбираем наиболее используемый: {chosen_framework} ({most_used[1]} использований)")
            else:
                chosen_framework = self._choose_by_priority(qt_frameworks)
        else:
            chosen_framework = self._choose_by_priority(qt_frameworks)

        # Добавляем только выбранный фреймворк
        self.plugin_modules.add(chosen_framework)

        # Удаляем остальные Qt пакеты из включаемых (без дубликатов сообщений)
        excluded_frameworks = set()
        for fw in qt_frameworks:
            if fw != chosen_framework and fw not in excluded_frameworks:
                excluded_frameworks.add(fw)
                # Удаляем все пакеты этого фреймворка
                packages_to_remove = [pkg for pkg in self.external_packages
                                      if pkg.split('.')[0].lower() == fw]
                for pkg in packages_to_remove:
                    self.external_packages.discard(pkg)
                    self.included_packages.discard(pkg)
                print(f"🚫 Исключаем {fw} для избежания конфликтов")

    def _count_qt_usage_in_code(self):
        """Подсчитывает реальное использование Qt фреймворков в коде"""
        qt_usage = defaultdict(int)

        qt_patterns = {
            'pyside6': [r'from\s+PySide6', r'import\s+PySide6'],
            'pyqt6': [r'from\s+PyQt6', r'import\s+PyQt6'],
            'pyside2': [r'from\s+PySide2', r'import\s+PySide2'],
            'pyqt5': [r'from\s+PyQt5', r'import\s+PyQt5'],
        }

        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                for framework, patterns in qt_patterns.items():
                    for pattern in patterns:
                        matches = len(re.findall(pattern, content, re.IGNORECASE))
                        qt_usage[framework] += matches

            except Exception:
                continue

        return dict(qt_usage)

    def _choose_by_priority(self, qt_frameworks):
        """Выбирает Qt фреймворк по приоритету"""
        # Проверяем переменную окружения
        preferred_qt = os.environ.get('PREFERRED_QT_FRAMEWORK', '').lower()
        if preferred_qt in qt_frameworks:
            print(f"🎯 Выбираем из переменной окружения PREFERRED_QT_FRAMEWORK: {preferred_qt}")
            return preferred_qt

        # Приоритет: PySide6 > PyQt6 > PySide2 > PyQt5 (PySide предпочтительнее)
        priority_order = ['pyside6', 'pyqt6', 'pyside2', 'pyqt5']

        for fw in priority_order:
            if fw in qt_frameworks:
                print(f"🎯 Выбираем по приоритету: {fw} (PySide предпочтительнее PyQt)")
                return fw

        # Если ничего не найдено, берем первый
        return qt_frameworks[0]

    def _analyze_qt_usage(self):
        """Анализирует использование Qt для лучшего выбора фреймворка"""
        qt_imports = defaultdict(list)

        # Анализируем импорты Qt в файлах
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Ищем Qt импорты
                qt_patterns = {
                    'pyqt5': [r'from\s+PyQt5', r'import\s+PyQt5'],
                    'pyside2': [r'from\s+PySide2', r'import\s+PySide2'],
                    'pyqt6': [r'from\s+PyQt6', r'import\s+PyQt6'],
                    'pyside6': [r'from\s+PySide6', r'import\s+PySide6'],
                }

                for framework, patterns in qt_patterns.items():
                    for pattern in patterns:
                        matches = re.findall(pattern, content, re.IGNORECASE)
                        qt_imports[framework].extend(matches)

            except Exception:
                continue

        return qt_imports

    def _get_nuitka_version(self):
        """Получает версию Nuitka"""
        try:
            import subprocess
            result = subprocess.run(['python', '-m', 'nuitka', '--version'],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return None

    def _analyze_package_dependencies(self):
        """Анализирует зависимости пакетов для определения включаемых модулей"""
        # Пакеты, которые нужно включать целиком
        include_whole_packages = {
            'numpy', 'scipy', 'pandas', 'matplotlib', 'sklearn', 'torch',
            'tensorflow', 'keras', 'cv2', 'PIL', 'skimage', 'networkx',
            'plotly', 'dash', 'streamlit', 'flask', 'django', 'fastapi',
            'requests', 'urllib3', 'aiohttp', 'websockets',
            'sqlalchemy', 'pymongo', 'redis', 'celery',
            'cryptography', 'jwt', 'passlib', 'bcrypt'
        }

        for package in self.external_packages:
            package_root = package.split('.')[0]
            if package_root in include_whole_packages:
                self.included_packages.add(package_root)

        # Модули для исключения (уменьшение размера)
        exclude_modules = {
            'test', 'tests', 'testing', 'unittest', 'doctest', 'pdb',
            'IPython', 'jupyter', 'notebook', 'spyder',
            'setuptools', 'pip', 'wheel', 'distutils',
            'pywin32', 'win32api', 'win32con'  # Исключаем на не-Windows системах
        }

        if platform.system() != 'Windows':
            self.excluded_modules.update({'pywin32', 'win32api', 'win32con', 'winsound'})

        self.excluded_modules.update(exclude_modules)

    def generate_nuitka_command(self,
                                app_name: Optional[str] = None,
                                standalone: bool = True,
                                onefile: bool = False,
                                enable_console: bool = True,
                                icon_path: Optional[str] = None,
                                output_dir: Optional[str] = None) -> str:
        """Генерирует команду Nuitka"""

        if app_name is None:
            app_name = Path(self.main_script).stem

        cmd_parts = ['python', '-m', 'nuitka']

        # Базовые параметры
        if standalone:
            cmd_parts.append('--standalone')
        if onefile:
            cmd_parts.append('--onefile')

        # Консоль/GUI
        if not enable_console:
            if platform.system() == 'Windows':
                cmd_parts.append('--windows-disable-console')
            else:
                cmd_parts.append('--disable-console')

        # Оптимизации
        cmd_parts.extend([
            '--assume-yes-for-downloads',
            '--enable-plugin=anti-bloat',
        ])

        # Плагины
        for plugin in sorted(self.plugin_modules):
            cmd_parts.append(f'--enable-plugin={plugin}')

        # Включение пакетов
        for package in sorted(self.included_packages):
            cmd_parts.append(f'--include-package={package}')

        # Исключение модулей
        for module in sorted(self.excluded_modules):
            cmd_parts.append(f'--nofollow-import-to={module}')

        # Файлы данных (ограничиваем количество для читаемости)
        for data_file in list(self.data_files)[:10]:
            src_path = str(data_file).replace('\\', '/')
            dst_path = str(data_file).replace('\\', '/')
            cmd_parts.append(f'--include-data-file={src_path}={dst_path}')

        # Папки данных
        for data_dir in self.data_dirs:
            src_path = str(data_dir).replace('\\', '/')
            dst_path = str(data_dir).replace('\\', '/')
            cmd_parts.append(f'--include-data-dir={src_path}={dst_path}')

        # Иконка
        if icon_path and Path(icon_path).exists():
            icon_path = str(Path(icon_path)).replace('\\', '/')
            if platform.system() == 'Windows':
                cmd_parts.append(f'--windows-icon-from-ico={icon_path}')
            elif platform.system() == 'Darwin':
                cmd_parts.append(f'--macos-app-icon={icon_path}')
            else:
                cmd_parts.append(f'--linux-onefile-icon={icon_path}')

        # Выходная папка
        if output_dir:
            output_path = str(Path(output_dir)).replace('\\', '/')
            cmd_parts.append(f'--output-dir={output_path}')
        else:
            cmd_parts.append('--output-dir=build')

        # Имя приложения (без расширения)
        if app_name != Path(self.main_script).stem:
            cmd_parts.append(f'--output-filename={app_name}')

        # Главный скрипт ДОЛЖЕН быть последним аргументом
        main_script_path = str(Path(self.main_script)).replace('\\', '/')
        cmd_parts.append(main_script_path)

        return ' '.join(f'"{part}"' if ' ' in part else part for part in cmd_parts)

    def generate_flexmontage_command(self, app_name: str = "FlexMontageStudio") -> str:
        """Генерирует оптимизированную команду Nuitka для FlexMontage Studio"""
        
        # Определяем иконку
        icon_path = None
        for icon_file in ['icon.icns', 'icon.ico']:
            icon_file_path = self.project_path / icon_file
            if icon_file_path.exists():
                icon_path = str(icon_file_path)
                break
        
        cmd_parts = ['python', '-m', 'nuitka']
        
        # Базовые параметры для GUI приложения
        cmd_parts.extend([
            '--standalone',
            '--assume-yes-for-downloads',
            '--enable-plugin=anti-bloat',
        ])
        
        # Отключаем консоль для GUI
        if platform.system() == 'Windows':
            cmd_parts.append('--windows-disable-console')
        else:
            cmd_parts.append('--disable-console')
        
        # PySide6 плагин (приоритетный)
        cmd_parts.append('--enable-plugin=pyside6')
        
        # Плагины для аудио/видео обработки (только существующие)
        video_audio_plugins = {
            'multiprocessing': 'multiprocessing'
        }
        
        for package in self.external_packages:
            package_name = package.split('.')[0].lower()
            if package_name in video_audio_plugins:
                plugin_name = video_audio_plugins[package_name]
                cmd_parts.append(f'--enable-plugin={plugin_name}')
        
        # Включаем критичные пакеты целиком (только те что реально есть)
        critical_packages = ['pandas', 'PIL', 'aiohttp', 'requests', 'openpyxl', 'cryptography', 'numpy', 'whisper']
        
        for package in critical_packages:
            if any(pkg.lower().startswith(package.lower()) for pkg in self.external_packages):
                cmd_parts.append(f'--include-package={package}')
        
        # Включаем специфичные модули FlexMontage Studio
        flexmontage_modules = [
            'ui', 'core', 'config', 'lic'
        ]
        
        for module_dir in flexmontage_modules:
            module_path = self.project_path / module_dir
            if module_path.exists():
                cmd_parts.append(f'--include-package-data={module_dir}')
        
        # Включаем папки данных
        data_dirs = ['ffmpeg']
        for data_dir in data_dirs:
            data_dir_path = self.project_path / data_dir
            if data_dir_path.exists() and data_dir_path.is_dir():
                cmd_parts.append(f'--include-data-dir={data_dir}={data_dir}')
        
        # Включаем файлы данных
        data_files = [
            'channels.json=channels.json',
            'licenses.json=licenses.json',
            'styles.qss=styles.qss'
        ]
        
        for data_spec in data_files:
            src_file = data_spec.split('=')[0]
            if (self.project_path / src_file).exists():
                cmd_parts.append(f'--include-data-file={data_spec}')
        
        # Исключаем ненужные модули для уменьшения размера
        exclude_modules = [
            'test', 'tests', 'testing', 'unittest', 'doctest',
            'IPython', 'jupyter', 'notebook', 'spyder',
            'setuptools', 'pip', 'wheel', 'distutils',
            'matplotlib.tests', 'numpy.tests', 'pandas.tests',
            'PyQt5', 'PyQt6', 'PySide2'  # Исключаем другие Qt фреймворки
        ]
        
        for module in exclude_modules:
            cmd_parts.append(f'--nofollow-import-to={module}')
        
        # Иконка приложения
        if icon_path:
            if platform.system() == 'Windows':
                cmd_parts.append(f'--windows-icon-from-ico={icon_path}')
            elif platform.system() == 'Darwin':
                cmd_parts.append(f'--macos-app-icon={icon_path}')
                # Дополнительные настройки для macOS
                cmd_parts.extend([
                    '--macos-create-app-bundle',
                    f'--macos-app-name={app_name}',
                    '--macos-app-version=1.0.0'
                ])
        
        # Вывод в папку dist
        cmd_parts.append('--output-dir=dist')
        
        # Имя приложения
        if app_name != "startup":
            cmd_parts.append(f'--output-filename={app_name}')
        
        # Оптимизации для производительности
        cmd_parts.extend([
            '--remove-output',  # Удаляет старые файлы сборки
            '--warn-implicit-exceptions',
            '--warn-unusual-code'
        ])
        
        # Главный скрипт последним
        cmd_parts.append('startup.py')
        
        return ' '.join(f'"{part}"' if ' ' in part else part for part in cmd_parts)

    def save_command_to_file(self, command: str, filename: str = "build_nuitka.sh"):
        """Сохраняет команду в исполняемый файл"""

        # Разбиваем длинную команду на строки для читаемости
        cmd_parts = command.split(' ')
        formatted_command = []
        current_line = []
        line_length = 0

        for part in cmd_parts:
            if line_length + len(part) + 1 > 80 and current_line:  # Максимальная длина строки
                formatted_command.append(' '.join(current_line) + ' \\')
                current_line = ['    ' + part]  # Отступ для продолжения
                line_length = len(part) + 4
            else:
                current_line.append(part)
                line_length += len(part) + 1

        if current_line:
            formatted_command.append(' '.join(current_line))

        multi_line_command = '\n'.join(formatted_command)

        script_content = f"""#!/bin/bash
# Автоматически сгенерированный скрипт сборки Nuitka
# Проект: {self.project_path.name}
# Главный файл: {self.main_script}
# Сгенерировано: Nuitka Command Generator

echo "🚀 Начинаем сборку с Nuitka..."
echo "📁 Проект: {self.project_path}"
echo "📄 Главный файл: {self.main_script}"
echo ""

# Проверяем наличие Nuitka
if ! python -c "import nuitka" 2>/dev/null; then
    echo "❌ Nuitka не установлена. Устанавливаем..."
    pip install nuitka
fi

# Создаем папку сборки если не существует
mkdir -p build

echo "⚙️  Выполняем сборку..."
{multi_line_command}

echo ""
if [ $? -eq 0 ]; then
    echo "✅ Сборка завершена успешно!"
    echo "📁 Результат в папке: build/"
    ls -la build/
else
    echo "❌ Ошибка при сборке!"
    exit 1
fi
"""

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(script_content)

        # Делаем файл исполняемым на Unix системах
        if platform.system() != 'Windows':
            os.chmod(filename, 0o755)

        print(f"📝 Скрипт сборки сохранен: {filename}")

        if platform.system() == 'Windows':
            # Создаем также .bat файл для Windows
            bat_filename = filename.replace('.sh', '.bat')

            # Форматируем команду для Windows
            win_command = command.replace('/', '\\')

            bat_content = f"""@echo off
REM Автоматически сгенерированный скрипт сборки Nuitka
REM Проект: {self.project_path.name}
REM Главный файл: {self.main_script}

echo 🚀 Начинаем сборку с Nuitka...
echo 📁 Проект: {self.project_path}
echo 📄 Главный файл: {self.main_script}
echo.

REM Проверяем наличие Nuitka
python -c "import nuitka" 2>nul
if errorlevel 1 (
    echo ❌ Nuitka не установлена. Устанавливаем...
    pip install nuitka
)

REM Создаем папку сборки
if not exist build mkdir build

echo ⚙️  Выполняем сборку...
{win_command}

echo.
if %errorlevel% equ 0 (
    echo ✅ Сборка завершена успешно!
    echo 📁 Результат в папке: build/
    dir build
) else (
    echo ❌ Ошибка при сборке!
    exit /b 1
)
pause
"""
            with open(bat_filename, 'w', encoding='utf-8') as f:
                f.write(bat_content)

            print(f"📝 Windows скрипт сохранен: {bat_filename}")

    def print_summary(self):
        """Выводит сводку анализа"""
        print("\n" + "=" * 70)
        print("АНАЛИЗ ПРОЕКТА ДЛЯ NUITKA")
        print("=" * 70)

        print(f"\n📊 СТАТИСТИКА:")
        print(f"   Главный скрипт: {self.main_script}")
        print(f"   Python файлов: {len(self.python_files)}")
        print(f"   Внешние пакеты: {len(self.external_packages)}")
        print(f"   Стандартная библиотека: {len(self.standard_library)}")
        print(f"   Локальные импорты: {len(self.local_imports)}")
        print(f"   Файлы данных: {len(self.data_files)}")
        print(f"   Папки данных: {len(self.data_dirs)}")

        if self.external_packages:
            print(f"\n📦 ВНЕШНИЕ ПАКЕТЫ:")
            sorted_packages = sorted(list(self.external_packages))
            for package in sorted_packages[:15]:
                count = self.import_counts.get(package, 0)
                print(f"   - {package} (использований: {count})")
            if len(self.external_packages) > 15:
                print(f"   ... и еще {len(self.external_packages) - 15}")

        if self.plugin_modules:
            print(f"\n🔌 ПЛАГИНЫ NUITKA:")
            for plugin in sorted(self.plugin_modules):
                print(f"   - {plugin}")

        if self.included_packages:
            print(f"\n📥 ВКЛЮЧАЕМЫЕ ПАКЕТЫ:")
            for package in sorted(self.included_packages):
                print(f"   - {package}")

        if self.data_dirs:
            print(f"\n📁 ПАПКИ ДАННЫХ:")
            for data_dir in sorted(self.data_dirs):
                print(f"   - {data_dir}")

        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        print(f"   1. Установите Nuitka: pip install nuitka")
        print(f"   2. Проверьте, что все зависимости установлены")
        print(f"   3. Для GUI приложений используйте --disable-console")
        print(f"   4. Для уменьшения размера используйте --onefile")
        print(f"   5. Тестируйте результат на чистой системе")


def main():
    parser = argparse.ArgumentParser(
        description='Генератор команд Nuitka на основе анализа проекта'
    )
    parser.add_argument('main_script', nargs='?', help='Путь к главному Python скрипту')
    parser.add_argument('--project-path', '-p', default='.',
                        help='Путь к корню проекта (по умолчанию текущая папка)')
    parser.add_argument('--app-name', '-n', help='Имя приложения')
    parser.add_argument('--onefile', action='store_true',
                        help='Создать один исполняемый файл')
    parser.add_argument('--no-console', action='store_true',
                        help='Отключить консоль (для GUI приложений)')
    parser.add_argument('--icon', help='Путь к файлу иконки')
    parser.add_argument('--output-dir', '-o', help='Папка для результата')
    parser.add_argument('--save-script', '-s', help='Сохранить команду в скрипт')
    parser.add_argument('--no-standalone', action='store_true',
                        help='Не создавать standalone сборку')
    parser.add_argument('--list-plugins', action='store_true',
                        help='Показать доступные плагины Nuitka')
    parser.add_argument('--check-nuitka', action='store_true',
                        help='Проверить установку Nuitka')
    parser.add_argument('--force-qt', choices=['pyqt5', 'pyside2', 'pyqt6', 'pyside6'],
                        help='Принудительно выбрать Qt фреймворк')
    parser.add_argument('--exclude-qt', action='store_true',
                        help='Исключить все Qt плагины')
    parser.add_argument('--flexmontage', action='store_true',
                        help='Использовать оптимизированные настройки для FlexMontage Studio')

    args = parser.parse_args()

    # Проверка Nuitka
    if args.check_nuitka:
        try:
            import subprocess
            result = subprocess.run(['python', '-m', 'nuitka', '--version'],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print(f"✅ Nuitka установлена: {result.stdout.strip()}")
            else:
                print("❌ Nuitka не найдена")
                return 1
        except Exception as e:
            print(f"❌ Ошибка при проверке Nuitka: {e}")
            return 1
        return 0

    # Показ доступных плагинов
    if args.list_plugins:
        try:
            import subprocess
            result = subprocess.run(['python', '-m', 'nuitka', '--plugin-list'],
                                    capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                print("🔌 Доступные плагины Nuitka:")
                print("=" * 50)
                print(result.stdout)
            else:
                print("❌ Не удалось получить список плагинов")
                return 1
        except Exception as e:
            print(f"❌ Ошибка при получении списка плагинов: {e}")
            return 1
        return 0

    # Проверяем обязательный аргумент
    if not args.main_script:
        parser.print_help()
        return 1

    # Проверяем наличие главного скрипта
    main_script_path = Path(args.main_script)
    if not main_script_path.exists():
        print(f"❌ Ошибка: файл {args.main_script} не найден")
        return 1

    # Предупреждения о недостающих библиотеках
    missing_libs = []
    if not HAS_YAML:
        missing_libs.append('pyyaml')
    if not HAS_TOML:
        missing_libs.append('toml')

    if missing_libs:
        print("🔍 Для полного анализа конфигурационных файлов установите:")
        print(f"   pip install {' '.join(missing_libs)}")
        print()

    # Создаем генератор и анализируем проект
    generator = NuitkaCommandGenerator(args.project_path, args.main_script)
    generator.analyze_project()

    # Применяем пользовательские настройки Qt
    if args.force_qt:
        # Принудительно устанавливаем выбранный Qt фреймворк
        qt_frameworks = ['pyqt5', 'pyside2', 'pyqt6', 'pyside6']
        for fw in qt_frameworks:
            generator.plugin_modules.discard(fw)
        generator.plugin_modules.add(args.force_qt)
        print(f"🎯 Принудительно выбран Qt фреймворк: {args.force_qt}")

    elif args.exclude_qt:
        # Исключаем все Qt плагины
        qt_frameworks = ['pyqt5', 'pyside2', 'pyqt6', 'pyside6']
        for fw in qt_frameworks:
            generator.plugin_modules.discard(fw)
        print("🚫 Все Qt плагины исключены")

    # Генерируем команду
    if args.flexmontage:
        print("🎯 Использование оптимизированных настроек для FlexMontage Studio")
        command = generator.generate_flexmontage_command(
            app_name=args.app_name or "FlexMontageStudio"
        )
    else:
        command = generator.generate_nuitka_command(
            app_name=args.app_name,
            standalone=not args.no_standalone,
            onefile=args.onefile,
            enable_console=not args.no_console,
            icon_path=args.icon,
            output_dir=args.output_dir
        )

    # Выводим сводку
    generator.print_summary()

    # Выводим команду
    print(f"\n" + "=" * 70)
    print("КОМАНДА NUITKA")
    print("=" * 70)
    print()
    print(command)
    print()

    # Сохраняем в скрипт если нужно
    if args.save_script:
        generator.save_command_to_file(command, args.save_script)
    else:
        # Автоматически сохраняем скрипт
        script_name = f"build_{Path(args.main_script).stem}.sh"
        generator.save_command_to_file(command, script_name)

    print(f"\n🚀 Для сборки выполните:")
    if platform.system() == 'Windows':
        bat_name = f"build_{Path(args.main_script).stem}.bat"
        print(f"   {bat_name}")
        print(f"   или напрямую:")
    else:
        script_name = f"build_{Path(args.main_script).stem}.sh"
        print(f"   ./{script_name}")
        print(f"   или напрямую:")

    print(f"   {command}")

    return 0


if __name__ == "__main__":
    exit(main())