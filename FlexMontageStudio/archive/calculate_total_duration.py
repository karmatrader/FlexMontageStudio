#!/usr/bin/env python3
"""
Calculate total expected duration from concat_list.txt
"""

import re

def calculate_total_duration(concat_file_path):
    """Calculate total expected duration from concat_list.txt"""
    total_duration = 0.0
    duration_count = 0
    
    with open(concat_file_path, 'r') as f:
        lines = f.readlines()
    
    for line in lines:
        line = line.strip()
        if line.startswith("duration "):
            duration_match = re.search(r"duration (\d+\.\d+)", line)
            if duration_match:
                duration = float(duration_match.group(1))
                total_duration += duration
                duration_count += 1
                print(f"Segment {duration_count}: {duration:.6f}s")
    
    return total_duration, duration_count

def main():
    concat_file = "/Users/mikman/PycharmProjects/PythonProject/FlexMontageStudio/dist/TestChannel/Output/1/temp/concat_list.txt"
    
    print("=== Total Duration Calculation ===\n")
    
    total_expected, segment_count = calculate_total_duration(concat_file)
    
    print(f"\nTotal segments: {segment_count}")
    print(f"Total expected duration: {total_expected:.6f} seconds")
    print(f"Total expected duration: {total_expected/60:.2f} minutes")
    
    # Compare with actual final video
    final_video_duration = 209.422982  # From previous check
    difference = abs(final_video_duration - total_expected)
    
    print(f"\nFinal video actual duration: {final_video_duration:.6f} seconds")
    print(f"Difference: {difference:.6f} seconds ({difference*1000:.2f} milliseconds)")
    
    if difference < 0.1:
        print("✅ Final video duration matches expected duration (within 100ms tolerance)")
    else:
        print("❌ Final video duration differs significantly from expected duration")

if __name__ == "__main__":
    main()