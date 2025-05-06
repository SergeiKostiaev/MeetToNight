import logging
from math import radians, cos, sin, asin, sqrt
from typing import Tuple, Union

# Настройка логгирования
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

def parse_coordinates(coord: Union[str, float, int]) -> float:
    try:
        return float(coord)
    except ValueError:
        raise ValueError(f"Invalid coordinate value: {coord}")

def calculate_distance(loc1: Tuple[Union[str, float], Union[str, float]],
                       loc2: Tuple[Union[str, float], Union[str, float]]) -> float:
    try:
        lat1 = parse_coordinates(loc1[0])
        lon1 = parse_coordinates(loc1[1])
        lat2 = parse_coordinates(loc2[0])
        lon2 = parse_coordinates(loc2[1])

        # Проверка диапазона
        for lat in (lat1, lat2):
            if not (-90 <= lat <= 90):
                raise ValueError(f"Latitude out of bounds: {lat}")
        for lon in (lon1, lon2):
            if not (-180 <= lon <= 180):
                raise ValueError(f"Longitude out of bounds: {lon}")

        # Расчёт расстояния
        R = 6371  # радиус Земли в км
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))
        return R * c

    except Exception as e:
        logger.error("Error in calculate_distance: %s", e)
        raise

# Пример использования:
if __name__ == "__main__":
    try:
        user_location = ("55.7558", "37.6173")  # Москва (строки)
        target_location = (59.9343, 30.3351)     # Санкт-Петербург (числа)
        distance = calculate_distance(user_location, target_location)
        print(f"Distance: {distance:.2f} km")
    except Exception as e:
        logger.error("Error in start_search for 8180089374: %s", e)
