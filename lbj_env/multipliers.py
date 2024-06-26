import random

# Multiplier data with weights
MULTIPLIERS = [
    {
        'data': {17: 2, 18: 2, 19: 3, 20: 4, 21: 5, 'BJ': 6},
        'weight': 0,
        'name': 'Low',
        'index': 0 
    },
    {
        'data': {17: 2, 18: 3, 19: 4, 20: 5, 21: 6, 'BJ': 8},
        'weight': 0,
        'name': 'Low-Mid',
        'index': 1
    },
    {
        'data': {17: 2, 18: 3, 19: 4, 20: 5, 21: 8, 'BJ': 12},
        'weight': 0,
        'name': 'Mid',
        'index': 2
    },
    {
        'data': {17: 2, 18: 4, 19: 5, 20: 6, 21: 10, 'BJ': 15},
        'weight': 0,
        'name': 'Mid-High',
        'index': 3
    },
    {
        'data': {17: 2, 18: 5, 19: 6, 20: 8, 21: 12, 'BJ': 20},
        'weight': 0,
        'name': 'High',
        'index': 4
    },
    {
        'data': {17: 2, 18: 5, 19: 8, 20: 10, 21: 15, 'BJ': 25},
        'weight': 0,
        'name': 'Nadir',
        'index': 5
    }
]

def default_multiplier():
    return MULTIPLIERS[2]

def roll_multiplier():
    chosen = random.choices(MULTIPLIERS, weights=[item['weight'] for item in MULTIPLIERS])[0]
    return chosen

