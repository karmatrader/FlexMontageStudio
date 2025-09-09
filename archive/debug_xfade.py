#!/usr/bin/env python3
"""
Отладка XFade переходов в FlexMontageStudio
"""
import sys
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def debug_xfade_logic():
    """Отладка логики XFade расчетов"""
    print("🔍 Отладка логики XFade расчетов")
    print("=" * 50)
    
    # Симулируем типичные данные FlexMontageStudio
    test_cases = [
        {
            "name": "2 клипа по 5 секунд, переход 1с",
            "durations": [5.0, 5.0],
            "transition_duration": 1.0
        },
        {
            "name": "3 клипа по 4 секунды, переход 1с",
            "durations": [4.0, 4.0, 4.0],
            "transition_duration": 1.0
        },
        {
            "name": "4 клипа разной длительности, переход 0.5с",
            "durations": [3.0, 4.5, 2.8, 3.2],
            "transition_duration": 0.5
        }
    ]
    
    for case in test_cases:
        print(f"\n📊 {case['name']}")
        print("-" * len(case['name']) + "---")
        
        durations = case["durations"]
        transition_duration = case["transition_duration"]
        num_clips = len(durations)
        num_transitions = num_clips - 1
        
        print(f"Исходные длительности: {[f'{d:.1f}с' for d in durations]}")
        print(f"Длительность перехода: {transition_duration}с")
        print(f"Количество переходов: {num_transitions}")
        
        # Рассчитываем offsets как в FlexMontageStudio
        filter_parts = []
        current_stream = "[0:v]"
        
        for i in range(num_clips - 1):
            if i == 0:
                # Первый переход
                offset = durations[i] - transition_duration
                xfade_filter = f"[0:v][1:v]xfade=transition=fade:duration={transition_duration:.1f}:offset={offset:.1f}[v0]"
                print(f"  Переход 1: offset={offset:.1f}с")
            else:
                # Последующие переходы
                prev_result_duration = sum(durations[:i+1]) - i * transition_duration
                offset = prev_result_duration - transition_duration
                xfade_filter = f"[v{i-1}][{i+1}:v]xfade=transition=fade:duration={transition_duration:.1f}:offset={offset:.1f}[v{i}]"
                print(f"  Переход {i+1}: prev_duration={prev_result_duration:.1f}с, offset={offset:.1f}с")
            
            filter_parts.append(xfade_filter)
        
        # Финальная длительность
        total_expected = sum(durations) - num_transitions * transition_duration
        print(f"Ожидаемая итоговая длительность: {total_expected:.1f}с")
        
        # Показываем filter_complex
        filter_complex = ";".join(filter_parts)
        print(f"Filter complex: {filter_complex}")

def check_video_files():
    """Проверка готовых видео файлов для тестирования"""
    from pathlib import Path
    import subprocess
    
    # Типичные пути к видео в FlexMontageStudio
    test_paths = [
        "/Users/mikman/Youtube/Структура/1 ЗВЁЗДНЫЕ ТАЙНЫ TV/temp",
        "/Users/mikman/PycharmProjects/PythonProject/FlexMontageStudio/temp"
    ]
    
    print("\n🎥 Поиск готовых видео файлов для тестирования:")
    found_videos = []
    
    for test_path in test_paths:
        path = Path(test_path)
        if path.exists():
            videos = list(path.glob("*.mp4"))
            if videos:
                print(f"📁 {test_path}: найдено {len(videos)} видео")
                for video in videos[:3]:  # Показываем первые 3
                    try:
                        # Получаем длительность
                        cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", 
                               "-of", "default=noprint_wrappers=1:nokey=1", str(video)]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                        if result.returncode == 0:
                            duration = float(result.stdout.strip())
                            print(f"  • {video.name}: {duration:.1f}с")
                            found_videos.append((str(video), duration))
                    except:
                        print(f"  • {video.name}: ошибка получения длительности")
            else:
                print(f"📁 {test_path}: видео не найдено")
        else:
            print(f"📁 {test_path}: папка не существует")
    
    if len(found_videos) >= 2:
        print(f"\n✅ Найдено достаточно видео для тестирования XFade!")
        return found_videos[:3]  # Возвращаем до 3 видео
    else:
        print(f"\n⚠️ Недостаточно видео для тестирования (найдено: {len(found_videos)})")
        return []

if __name__ == "__main__":
    debug_xfade_logic()
    
    # Проверяем доступные видео файлы
    videos = check_video_files()
    
    if videos:
        print(f"\n💡 Рекомендация:")
        print(f"Для тестирования XFade в FlexMontageStudio используйте следующие файлы:")
        for video, duration in videos:
            print(f"  • {video} ({duration:.1f}с)")
    
    print(f"\n🔧 Для отладки в FlexMontageStudio:")
    print(f"1. Включите переходы в интерфейсе")
    print(f"2. Выберите метод 'XFade'")
    print(f"3. Установите длительность перехода 1.0с")
    print(f"4. Запустите монтаж и проверьте логи")