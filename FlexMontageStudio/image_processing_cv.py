"""
Модуль обработки изображений с использованием OpenCV
Заменяет функциональность PIL/Pillow с расширенными возможностями
"""

import cv2
import numpy as np
import logging
from pathlib import Path
from typing import Tuple, Optional, Union, List
import os

# Подавляем OpenCV warnings для imread (они не критичны когда есть fallback)
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '0'
os.environ['OPENCV_IO_MAX_IMAGE_PIXELS'] = '1073741824'  # 1GB limit

logger = logging.getLogger(__name__)

# Поддерживаемые форматы изображений и видео
SUPPORTED_IMAGE_FORMATS = (
    '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif', 
    '.tga', '.ico', '.gif'
)

SUPPORTED_VIDEO_FORMATS = (
    '.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v', 
    '.3gp', '.ts'
)

SUPPORTED_FORMATS = SUPPORTED_IMAGE_FORMATS + SUPPORTED_VIDEO_FORMATS


class ImageProcessorCV:
    """Класс для обработки изображений с использованием OpenCV"""
    
    def __init__(self):
        """Инициализация процессора изображений"""
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def _safe_imread(self, image_path: str) -> Optional[np.ndarray]:
        """
        Безопасная загрузка изображений для Windows с Unicode путями
        
        Args:
            image_path: Путь к файлу изображения
            
        Returns:
            np.ndarray или None при ошибке
        """
        try:
            # Метод 1: Стандартный cv2.imread (может выдать warning для проблемных путей)
            img = cv2.imread(image_path, cv2.IMREAD_COLOR)
            if img is not None:
                return img
            
            # Метод 2: Загрузка через numpy для путей с Unicode (Windows)
            import sys
            if sys.platform == "win32":
                try:
                    # Читаем файл в память и декодируем через cv2.imdecode
                    with open(image_path, 'rb') as f:
                        file_bytes = f.read()
                    
                    # Конвертируем в numpy array
                    nparr = np.frombuffer(file_bytes, np.uint8)
                    
                    # Декодируем изображение
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if img is not None:
                        self.logger.debug(f"Загружено через imdecode: {image_path}")
                        return img
                    
                except Exception as e:
                    self.logger.debug(f"Метод imdecode не сработал для {image_path}: {e}")
            
            # Метод 3: Попытка с PIL как fallback
            try:
                from PIL import Image
                pil_image = Image.open(image_path)
                
                # Конвертируем PIL в OpenCV формат
                if pil_image.mode == 'RGBA':
                    pil_image = pil_image.convert('RGB')
                elif pil_image.mode == 'P':
                    pil_image = pil_image.convert('RGB')
                elif pil_image.mode == 'L':
                    pil_image = pil_image.convert('RGB')
                
                # PIL использует RGB, OpenCV - BGR
                opencv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
                self.logger.debug(f"Загружено через PIL fallback: {image_path}")
                return opencv_image
                
            except ImportError:
                self.logger.debug("PIL не доступен для fallback")
            except Exception as e:
                self.logger.debug(f"PIL fallback не сработал для {image_path}: {e}")
            
            return None
            
        except Exception as e:
            self.logger.error(f"Все методы загрузки не сработали для {image_path}: {e}")
            return None
    
    def _safe_imwrite(self, output_path: str, image: np.ndarray, encode_params: list) -> bool:
        """
        Безопасное сохранение изображений для Windows с Unicode путями
        
        Args:
            output_path: Путь для сохранения
            image: Изображение для сохранения
            encode_params: Параметры кодирования
            
        Returns:
            bool: True если успешно сохранено
        """
        try:
            # Метод 1: Стандартный cv2.imwrite
            success = cv2.imwrite(output_path, image, encode_params)
            if success:
                return True
            
            # Метод 2: Сохранение через imencode для путей с Unicode (Windows)
            import sys
            if sys.platform == "win32":
                try:
                    ext = Path(output_path).suffix.lower()
                    
                    # Выбираем формат для imencode
                    if ext in ['.jpg', '.jpeg']:
                        ext_for_encode = '.jpg'
                    elif ext == '.png':
                        ext_for_encode = '.png'
                    elif ext == '.webp':
                        ext_for_encode = '.webp'
                    else:
                        ext_for_encode = '.jpg'  # fallback
                    
                    # Кодируем изображение в память
                    success, encoded_img = cv2.imencode(ext_for_encode, image, encode_params)
                    if success:
                        # Записываем в файл
                        with open(output_path, 'wb') as f:
                            f.write(encoded_img.tobytes())
                        self.logger.debug(f"Сохранено через imencode: {output_path}")
                        return True
                    
                except Exception as e:
                    self.logger.debug(f"Метод imencode не сработал для {output_path}: {e}")
            
            # Метод 3: PIL fallback
            try:
                from PIL import Image
                
                # Конвертируем BGR в RGB для PIL
                rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(rgb_image)
                
                # Определяем параметры сохранения для PIL
                ext = Path(output_path).suffix.lower()
                if ext in ['.jpg', '.jpeg']:
                    # Для JPEG извлекаем качество из encode_params
                    quality = 95  # default
                    for i in range(0, len(encode_params), 2):
                        if encode_params[i] == cv2.IMWRITE_JPEG_QUALITY:
                            quality = encode_params[i + 1]
                            break
                    pil_image.save(output_path, 'JPEG', quality=quality)
                elif ext == '.png':
                    pil_image.save(output_path, 'PNG')
                elif ext == '.webp':
                    # Для WebP извлекаем качество
                    quality = 95  # default
                    for i in range(0, len(encode_params), 2):
                        if encode_params[i] == cv2.IMWRITE_WEBP_QUALITY:
                            quality = encode_params[i + 1]
                            break
                    pil_image.save(output_path, 'WEBP', quality=quality)
                else:
                    pil_image.save(output_path)
                
                self.logger.debug(f"Сохранено через PIL fallback: {output_path}")
                return True
                
            except ImportError:
                self.logger.debug("PIL не доступен для fallback сохранения")
            except Exception as e:
                self.logger.debug(f"PIL fallback не сработал для {output_path}: {e}")
            
            return False
            
        except Exception as e:
            self.logger.error(f"Все методы сохранения не сработали для {output_path}: {e}")
            return False
    
    def load_image(self, image_path: Union[str, Path]) -> Optional[np.ndarray]:
        """
        Загрузка изображения с использованием OpenCV
        
        Args:
            image_path: Путь к изображению
            
        Returns:
            np.ndarray: Загруженное изображение в формате BGR или None при ошибке
        """
        try:
            image_path = str(image_path)
            
            # Проверяем существование файла перед попыткой загрузки
            if not Path(image_path).exists():
                self.logger.error(f"Файл изображения не существует: {image_path}")
                return None
            
            # Дополнительная диагностика для Windows
            if not Path(image_path).is_file():
                self.logger.error(f"Путь не является файлом: {image_path}")
                return None
            
            # Безопасная загрузка для Windows с Unicode путями
            img = self._safe_imread(image_path)
            
            if img is None:
                self.logger.error(f"OpenCV не смог загрузить изображение: {image_path}")
                self.logger.error(f"Размер файла: {Path(image_path).stat().st_size} байт")
                
                # Дополнительная диагностика для Windows
                try:
                    with open(image_path, 'rb') as f:
                        header = f.read(16)
                        self.logger.error(f"Заголовок файла: {header.hex()[:32]}")
                        
                        # Проверяем магические числа
                        if header.startswith(b'\xff\xd8\xff'):
                            self.logger.error("Файл выглядит как JPEG")
                        elif header.startswith(b'\x89PNG'):
                            self.logger.error("Файл выглядит как PNG")
                        elif header.startswith(b'RIFF') and b'WEBP' in header:
                            self.logger.error("Файл выглядит как WebP")
                        else:
                            self.logger.error("Неизвестный формат файла")
                except Exception as diagnostic_e:
                    self.logger.error(f"Ошибка диагностики файла: {diagnostic_e}")
                
                return None
                
            self.logger.debug(f"Загружено изображение {image_path}: {img.shape}")
            return img
            
        except Exception as e:
            self.logger.error(f"Ошибка загрузки изображения {image_path}: {e}")
            return None
    
    def save_image(self, image: np.ndarray, output_path: Union[str, Path], 
                   quality: int = 95) -> bool:
        """
        Сохранение изображения с оптимизацией
        
        Args:
            image: Изображение для сохранения
            output_path: Путь для сохранения
            quality: Качество JPEG (1-100)
            
        Returns:
            bool: True если успешно сохранено
        """
        try:
            output_path = str(output_path)
            ext = Path(output_path).suffix.lower()
            
            if ext in ['.jpg', '.jpeg']:
                # Параметры для JPEG
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
            elif ext == '.png':
                # Параметры для PNG (сжатие без потерь)
                encode_params = [cv2.IMWRITE_PNG_COMPRESSION, 6]
            elif ext == '.webp':
                # Параметры для WebP
                encode_params = [cv2.IMWRITE_WEBP_QUALITY, quality]
            else:
                encode_params = []
            
            # Безопасное сохранение для Windows с Unicode путями
            success = self._safe_imwrite(output_path, image, encode_params)
            
            if success:
                self.logger.debug(f"Изображение сохранено: {output_path}")
                return True
            else:
                self.logger.error(f"Не удалось сохранить изображение: {output_path}")
                return False
                
        except Exception as e:
            self.logger.error(f"Ошибка сохранения изображения {output_path}: {e}")
            return False
    
    def resize_image(self, image: np.ndarray, target_size: Tuple[int, int], 
                     interpolation: int = cv2.INTER_LANCZOS4) -> np.ndarray:
        """
        Изменение размера изображения
        
        Args:
            image: Исходное изображение
            target_size: Целевой размер (width, height)
            interpolation: Метод интерполяции
            
        Returns:
            np.ndarray: Изображение с измененным размером
        """
        try:
            resized = cv2.resize(image, target_size, interpolation=interpolation)
            self.logger.debug(f"Размер изменен с {image.shape[:2]} на {target_size}")
            return resized
            
        except Exception as e:
            self.logger.error(f"Ошибка изменения размера: {e}")
            return image
    
    def apply_gaussian_blur(self, image: np.ndarray, blur_radius: float) -> np.ndarray:
        """
        Применение размытия по Гауссу
        
        Args:
            image: Исходное изображение
            blur_radius: Радиус размытия
            
        Returns:
            np.ndarray: Размытое изображение
        """
        try:
            # Преобразуем радиус PIL в параметры OpenCV
            # PIL radius примерно соответствует sigma * 3
            sigma = blur_radius / 3.0
            
            # Размер ядра должен быть нечетным
            ksize = int(blur_radius * 2) | 1
            if ksize < 3:
                ksize = 3
            
            blurred = cv2.GaussianBlur(image, (ksize, ksize), sigma)
            self.logger.debug(f"Применено размытие: radius={blur_radius}, ksize={ksize}, sigma={sigma}")
            return blurred
            
        except Exception as e:
            self.logger.error(f"Ошибка размытия: {e}")
            return image
    
    def apply_bokeh_effect(self, image_path: Union[str, Path], output_path: Union[str, Path],
                          bokeh_config: dict) -> bool:
        """
        Применение эффекта боке с расширенными параметрами
        
        Args:
            image_path: Путь к исходному изображению
            output_path: Путь для сохранения результата
            bokeh_config: Конфигурация эффекта боке
            
        Returns:
            bool: True если успешно применен
        """
        try:
            img = self.load_image(image_path)
            if img is None:
                return False
            
            # Получаем параметры из конфигурации
            target_size = tuple(bokeh_config.get('bokeh_image_size', [1920, 1080]))
            blur_kernel = bokeh_config.get('bokeh_blur_kernel', [99, 99])
            blur_sigma = float(bokeh_config.get('bokeh_blur_sigma', 30))
            
            # Новые параметры
            blur_method = bokeh_config.get('bokeh_blur_method', 'gaussian')
            intensity = float(bokeh_config.get('bokeh_intensity', 0.8))
            focus_area = bokeh_config.get('bokeh_focus_area', 'center')
            transition_smoothness = int(bokeh_config.get('bokeh_transition_smoothness', 50))
            
            # Изменяем размер изображения
            img_resized = self.resize_image(img, target_size)
            
            # Создаем размытый фон
            if blur_method == 'gaussian':
                blurred_bg = cv2.GaussianBlur(img_resized, tuple(blur_kernel), blur_sigma)
            elif blur_method == 'motion':
                # Создаем ядро для motion blur
                kernel_size = max(blur_kernel)
                kernel = np.zeros((kernel_size, kernel_size))
                kernel[kernel_size//2, :] = np.ones(kernel_size)
                kernel = kernel / kernel_size
                blurred_bg = cv2.filter2D(img_resized, -1, kernel)
            elif blur_method == 'radial':
                # Радиальное размытие (упрощенная версия)
                blurred_bg = cv2.GaussianBlur(img_resized, tuple(blur_kernel), blur_sigma)
            else:
                blurred_bg = cv2.GaussianBlur(img_resized, tuple(blur_kernel), blur_sigma)
            
            # Создаем маску для области фокуса
            mask = self._create_focus_mask(target_size, focus_area, transition_smoothness)
            
            # Применяем интенсивность эффекта
            mask = (mask * intensity).astype(np.float32)
            mask = np.stack([mask, mask, mask], axis=2)
            
            # Смешиваем четкое изображение и размытый фон
            img_float = img_resized.astype(np.float32)
            blurred_float = blurred_bg.astype(np.float32)
            
            result = img_float * mask + blurred_float * (1 - mask)
            result = np.clip(result, 0, 255).astype(np.uint8)
            
            # Сохраняем результат
            return self.save_image(result, output_path)
            
        except Exception as e:
            self.logger.error(f"Ошибка применения эффекта боке: {e}")
            return False
    
    def _create_focus_mask(self, image_size: Tuple[int, int], focus_area: str, 
                          smoothness: int) -> np.ndarray:
        """
        Создание маски для области фокуса
        
        Args:
            image_size: Размер изображения (width, height)
            focus_area: Область фокуса ('center', 'top', 'bottom', 'left', 'right')
            smoothness: Плавность перехода (0-100)
            
        Returns:
            np.ndarray: Маска фокуса (0.0-1.0)
        """
        width, height = image_size
        y, x = np.ogrid[:height, :width]
        
        # Определяем центр области фокуса
        if focus_area == 'center':
            center_x, center_y = width // 2, height // 2
        elif focus_area == 'top':
            center_x, center_y = width // 2, height // 4
        elif focus_area == 'bottom':
            center_x, center_y = width // 2, 3 * height // 4
        elif focus_area == 'left':
            center_x, center_y = width // 4, height // 2
        elif focus_area == 'right':
            center_x, center_y = 3 * width // 4, height // 2
        else:
            center_x, center_y = width // 2, height // 2
        
        # Создаем радиальную маску
        distance = np.sqrt((x - center_x)**2 + (y - center_y)**2)
        max_distance = min(width, height) // 3
        
        # Применяем плавность
        smoothness_factor = smoothness / 100.0
        fade_distance = max_distance * (1 + smoothness_factor)
        
        mask = np.clip(1 - distance / fade_distance, 0, 1)
        
        return mask
    
    def apply_image_effects(self, image: np.ndarray, effects_config: dict) -> np.ndarray:
        """
        Применение дополнительных эффектов к изображению
        
        Args:
            image: Исходное изображение
            effects_config: Конфигурация эффектов
            
        Returns:
            np.ndarray: Обработанное изображение
        """
        result = image.copy()
        
        try:
            # Повышение резкости
            if effects_config.get('sharpen_enabled', False):
                strength = float(effects_config.get('sharpen_strength', 1.5))
                result = self._apply_sharpen(result, strength)
            
            # Коррекция контраста
            if effects_config.get('contrast_enabled', False):
                factor = float(effects_config.get('contrast_factor', 1.2))
                result = self._apply_contrast(result, factor)
            
            # Коррекция яркости
            if effects_config.get('brightness_enabled', False):
                delta = int(effects_config.get('brightness_delta', 10))
                result = self._apply_brightness(result, delta)
            
            # Насыщенность
            if effects_config.get('saturation_enabled', False):
                factor = float(effects_config.get('saturation_factor', 1.1))
                result = self._apply_saturation(result, factor)
            
            # Виньетирование
            if effects_config.get('vignette_enabled', False):
                strength = float(effects_config.get('vignette_strength', 0.3))
                result = self._apply_vignette(result, strength)
            
            # Улучшение краев
            if effects_config.get('edge_enhancement', False):
                result = self._apply_edge_enhancement(result)
            
            # Подавление шума
            if effects_config.get('noise_reduction', False):
                result = self._apply_noise_reduction(result)
            
            # Цветовая коррекция по гистограмме
            if effects_config.get('histogram_equalization', False):
                result = self._apply_histogram_equalization(result)
            
            # Фильтры стиля
            style_filter = effects_config.get('style_filter', 'none')
            if style_filter != 'none':
                result = self._apply_style_filter(result, style_filter)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Ошибка применения эффектов: {e}")
            return image
    
    def _apply_sharpen(self, image: np.ndarray, strength: float) -> np.ndarray:
        """Повышение резкости"""
        kernel = np.array([[-1, -1, -1],
                          [-1, 9 * strength, -1],
                          [-1, -1, -1]])
        return cv2.filter2D(image, -1, kernel)
    
    def _apply_contrast(self, image: np.ndarray, factor: float) -> np.ndarray:
        """Коррекция контраста"""
        return cv2.convertScaleAbs(image, alpha=factor, beta=0)
    
    def _apply_brightness(self, image: np.ndarray, delta: int) -> np.ndarray:
        """Коррекция яркости"""
        return cv2.convertScaleAbs(image, alpha=1.0, beta=delta)
    
    def _apply_saturation(self, image: np.ndarray, factor: float) -> np.ndarray:
        """Коррекция насыщенности"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = hsv[:, :, 1] * factor
        hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    def _apply_vignette(self, image: np.ndarray, strength: float) -> np.ndarray:
        """Виньетирование"""
        h, w = image.shape[:2]
        y, x = np.ogrid[:h, :w]
        center_x, center_y = w // 2, h // 2
        
        distance = np.sqrt((x - center_x)**2 + (y - center_y)**2)
        max_distance = np.sqrt(center_x**2 + center_y**2)
        
        vignette = 1 - (distance / max_distance) * strength
        vignette = np.clip(vignette, 0, 1)
        vignette = np.stack([vignette, vignette, vignette], axis=2)
        
        return (image * vignette).astype(np.uint8)
    
    def _apply_edge_enhancement(self, image: np.ndarray) -> np.ndarray:
        """Улучшение краев"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Laplacian(gray, cv2.CV_64F)
        edges = np.absolute(edges).astype(np.uint8)
        edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        return cv2.addWeighted(image, 0.8, edges, 0.2, 0)
    
    def _apply_noise_reduction(self, image: np.ndarray) -> np.ndarray:
        """Подавление шума"""
        return cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)
    
    def _apply_histogram_equalization(self, image: np.ndarray) -> np.ndarray:
        """Цветовая коррекция по гистограмме"""
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = cv2.equalizeHist(lab[:, :, 0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    
    def _apply_style_filter(self, image: np.ndarray, style: str) -> np.ndarray:
        """Применение фильтров стиля"""
        if style == 'sepia':
            kernel = np.array([[0.272, 0.534, 0.131],
                              [0.349, 0.686, 0.168],
                              [0.393, 0.769, 0.189]])
            return cv2.transform(image, kernel)
        
        elif style == 'grayscale':
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        
        elif style == 'vintage':
            # Винтажный эффект
            vintage = image.copy().astype(np.float32)
            vintage[:, :, 0] = vintage[:, :, 0] * 0.9  # Синий канал
            vintage[:, :, 1] = vintage[:, :, 1] * 1.1  # Зеленый канал  
            vintage[:, :, 2] = vintage[:, :, 2] * 1.2  # Красный канал
            return np.clip(vintage, 0, 255).astype(np.uint8)
        
        elif style == 'cool':
            # Холодные тона
            cool = image.copy().astype(np.float32)
            cool[:, :, 0] = cool[:, :, 0] * 1.3  # Синий канал
            cool[:, :, 2] = cool[:, :, 2] * 0.8  # Красный канал
            return np.clip(cool, 0, 255).astype(np.uint8)
        
        elif style == 'warm':
            # Теплые тона
            warm = image.copy().astype(np.float32)
            warm[:, :, 0] = warm[:, :, 0] * 0.8  # Синий канал
            warm[:, :, 2] = warm[:, :, 2] * 1.3  # Красный канал
            return np.clip(warm, 0, 255).astype(np.uint8)
        
        else:
            return image

    def apply_bokeh_sides_effect(self, image_path: Union[str, Path], output_path: Union[str, Path],
                                bokeh_config: dict) -> bool:
        """
        Применение эффекта боке по бокам для вертикальных изображений
        
        Args:
            image_path: Путь к исходному изображению
            output_path: Путь для сохранения результата
            bokeh_config: Конфигурация эффекта боке
            
        Returns:
            bool: True если успешно применен
        """
        try:
            img = self.load_image(image_path)
            if img is None:
                return False
            
            # Получаем параметры из конфигурации
            target_size = tuple(bokeh_config.get('bokeh_image_size', [1920, 1080]))
            target_width, target_height = target_size
            blur_sigma = float(bokeh_config.get('bokeh_blur_sigma', 30))
            
            # Получаем размеры исходного изображения
            orig_height, orig_width = img.shape[:2]
            orig_aspect = orig_width / orig_height
            target_aspect = target_width / target_height
            
            # Проверяем, нужно ли применять боке по бокам
            # Применяем боке по бокам когда изображение уже целевого разрешения (не хватает горизонтального пространства)
            if orig_aspect < target_aspect:
                # Изображение уже целевого - применяем боке по бокам
                
                # 1. Масштабируем по высоте для полного заполнения высоты кадра
                scale_factor = target_height / orig_height
                new_width = int(orig_width * scale_factor)
                new_height = target_height
                
                img_scaled = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
                
                # 2. Создаем фон из размытой версии изображения
                # Растягиваем изображение до целевого размера для создания фона
                img_stretched = cv2.resize(img, target_size, interpolation=cv2.INTER_LANCZOS4)
                
                # Размываем фон
                blurred_bg = cv2.GaussianBlur(img_stretched, (99, 99), blur_sigma)
                
                # 3. Размещаем масштабированное изображение по центру
                result = blurred_bg.copy()
                
                # Вычисляем позицию для центрирования
                x_offset = (target_width - new_width) // 2
                y_offset = 0  # Уже масштабировано по высоте
                
                # Размещаем четкое изображение по центру
                if x_offset >= 0:
                    result[y_offset:y_offset + new_height, x_offset:x_offset + new_width] = img_scaled
                else:
                    # Если масштабированное изображение шире целевого (что не должно происходить)
                    # обрезаем его по центру
                    crop_x = -x_offset
                    crop_width = target_width
                    img_cropped = img_scaled[:, crop_x:crop_x + crop_width]
                    result[:, :] = img_cropped
                
                # Сохраняем результат
                return self.save_image(result, output_path)
            else:
                # Изображение шире или равно целевому - обычное масштабирование без боке по бокам
                img_resized = self.resize_image(img, target_size)
                return self.save_image(img_resized, output_path)
            
        except Exception as e:
            self.logger.error(f"Ошибка применения эффекта боке по бокам: {e}")
            return False


# Функции обратной совместимости
def resize_and_blur(image_path: str, output_path: str, image_size: tuple, 
                   blur_radius: float) -> bool:
    """
    Функция обратной совместимости для изменения размера и размытия
    
    Args:
        image_path: Путь к исходному изображению
        output_path: Путь для сохранения
        image_size: Размер изображения (width, height)
        blur_radius: Радиус размытия
        
    Returns:
        bool: True если успешно обработано
    """
    processor = ImageProcessorCV()
    
    img = processor.load_image(image_path)
    if img is None:
        return False
    
    img_resized = processor.resize_image(img, image_size)
    img_blurred = processor.apply_gaussian_blur(img_resized, blur_radius)
    
    return processor.save_image(img_blurred, output_path)


def process_image_fixed_height(image_path: str, target_height: int) -> bool:
    """
    Функция обратной совместимости для обработки с фиксированной высотой
    
    Args:
        image_path: Путь к изображению
        target_height: Целевая высота
        
    Returns:
        bool: True если успешно обработано
    """
    processor = ImageProcessorCV()
    
    img = processor.load_image(image_path)
    if img is None:
        return False
    
    h, w = img.shape[:2]
    aspect_ratio = w / h
    target_width = int(target_height * aspect_ratio)
    
    img_resized = processor.resize_image(img, (target_width, target_height))
    
    return processor.save_image(img_resized, image_path)