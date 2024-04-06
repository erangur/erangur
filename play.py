import random

BET = 1
SPLIT_CHOICES = ['h', 's'] # Can you double?

MID_MULTIPLIERS = {
    4: 2,
    5: 2,
    6: 2,
    7: 2,
    8: 2,
    9: 2,
    10: 2,
    11: 2,
    12: 2,
    13: 2,
    14: 2,
    15: 2,
    16: 2,
    17: 2,
    18: 3,
    19: 4,
    20: 5,
    21: 6,
    22: 8  # Blackjack
}


# Card values
card_values = {
    'Ace': 11,  '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'Jack': 10, 'Queen': 10, 'King': 10
}

# Function to calculate the total value of a hand
def calculate_hand(hand):
    total = sum(card_values[card] for card in hand)
    if 'Ace' in hand and total > 21:
        total -= 10
    return total

choice_to_action = {
    'h': 'hit',
    's': 'stand',
    'd': 'double down',
    'p': 'split'
}

def make_choice(choices):
    choice = input("Do you want to " + " or ".join(choice_to_action[choice] + "(" + choice + ")" for choice in choices) + "? ")
    if choice in choices:
        return choice
    else:
        print("Invalid choice")
        return make_choice(choices)

def setup_hand():
    deck = ['Ace', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'Jack', 'Queen', 'King'] * 8
    random.shuffle(deck)
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]
    print("Dealer has a " + dealer_hand[0] + " showing.")
    multipliers = MID_MULTIPLIERS
    print("Chosen multipliers: " + str(multipliers))
    return deck, player_hand, dealer_hand, multipliers

def dealer_turn(deck, dealer_hand):
    while calculate_hand(dealer_hand) < 17:
        dealer_hand.append(deck.pop())
    return calculate_hand(dealer_hand)

def get_initial_choices(hand):
    choices = ['h', 's', 'd']
    if hand[0] == hand[1]:
        choices.append('p')
    return choices

def get_hit_choices(hand):
    if len(hand) == 2 and hand[0] == hand[1]:
        return ['h', 's', 'p']
    return ['h', 's']

def player_turn(deck, player_hand, choices, number_of_multipliers=0):
    print("Your hand: " + ", ".join(player_hand) + " (" + str(calculate_hand(player_hand)) + ")")
    player_hand_value = calculate_hand(player_hand)
    if (player_hand_value > 21):
        print("You busted with a hand of " + str(player_hand_value))
        return [(player_hand, number_of_multipliers)]
    if (player_hand_value == 21):
        print("You got a 21 with a hand of " + str(player_hand_value) + "!")
        return [(player_hand, number_of_multipliers)]
    
    choice = make_choice(choices)
    if choice == 'h':
        card = deck.pop()
        print("You drew a " + card)
        player_hand.append(card)
        return player_turn(deck, player_hand, get_hit_choices(player_hand), number_of_multipliers)
    elif choice == 's':
        return [(player_hand, number_of_multipliers)]
    elif choice == 'd':
        player_hand.append(deck.pop())
        print("After double, your hand is: " + ", ".join(player_hand))
        return [(player_hand, number_of_multipliers + 1)]
    elif choice == 'p':
        return player_turn(deck, [player_hand[0]], SPLIT_CHOICES) + player_turn(deck, [player_hand[1]], SPLIT_CHOICES)

def calculate_hand_cost(player_hands):
    return BET + sum(BET * (2 ** number_of_multipliers) for hand, number_of_multipliers in player_hands)

def play_hand(bankroll, current_multiplier):
    deck, player_hand, dealer_hand, multipliers = setup_hand()
    
    ### check blackjack

    player_initial_choices = get_initial_choices(player_hand)
    player_hands = player_turn(deck, player_hand, player_initial_choices)
    dealer_hand_value = dealer_turn(deck, dealer_hand)
    print("Dealer's hand: " + ", ".join(dealer_hand) + " (" + str(dealer_hand_value) + ")")
    hand_cost = calculate_hand_cost(player_hands)
    next_hand_multiplier = 1
    won_amount = 0
    for hand in player_hands:
        player_hand, number_of_multipliers = hand
        print("Player's hand: " + ", ".join(player_hand) + " (" + str(calculate_hand(player_hand)) + ")")
        print("Number of multipliers: " + str(number_of_multipliers))
        player_hand_value = calculate_hand(player_hand)
        if player_hand_value > 21:
            continue
        if dealer_hand_value < player_hand_value or dealer_hand_value > 21:
            won_amount += 2 * BET * (2 ** number_of_multipliers) * current_multiplier
            next_hand_multiplier = max(next_hand_multiplier, multipliers[player_hand_value])
        elif dealer_hand_value == player_hand_value:
            won_amount += BET
    
    print("hand cost: " + str(hand_cost))
    print("won amount: " + str(won_amount))
    return bankroll - hand_cost + won_amount, next_hand_multiplier

# Start the game
bankroll = 200
multiplier = 1
hand_count = 1
while True:
    print(f"\nYour bankroll: {bankroll}")

    if bankroll <= 0:
        print("You've run out of money. Game over!")
        break

    bankroll, multiplier = play_hand(bankroll, multiplier)
    print(f"Hand: {hand_count}, Bankroll: {bankroll}, Multiplier: {multiplier}")
    hand_count += 1

print(f"\nYou left the game with a bankroll of {bankroll}. Thanks for playing!")
