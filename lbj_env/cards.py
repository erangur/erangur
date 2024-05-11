import random

def random_card():
    return random.choice(['Ace', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'Jack', 'Queen', 'King'])


# Card values
card_values = {
    'Ace': 11, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'Jack': 10, 'Queen': 10, 'King': 10
}

def calculate_hand(hand):
    total = sum(card_values[card] for card in hand)
    num_aces = hand.count('Ace')
    while total > 21 and num_aces:
        total -= 10
        num_aces -= 1

    return total
    
def is_soft(hand):
    hand_value = calculate_hand(hand)
    minimal_value = sum(card_values[card] for card in hand) - hand.count('Ace') * 10
    return hand_value != minimal_value