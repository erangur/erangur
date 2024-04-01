import random

# Card values
card_values = {
    'Ace': 11,  '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'Jack': 10, 'Queen': 10, 'King': 10
}

# Multipliers for different hand values
multipliers = {
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

# Function to calculate the total value of a hand
def calculate_hand(hand):
    total = sum(card_values[card] for card in hand)
    if 'Ace' in hand and total > 21:
        total -= 10
    return total

# Function to set up a hand for testing
def setup_hand(player_hand, dealer_hand, player_total, dealer_total):
    player_hand.clear()
    dealer_hand.clear()
    player_hand.extend(['10', 'Ace'])
    dealer_hand.extend(['King', '7'])
    return player_total, dealer_total

# Function to play a game of blackjack
def play_blackjack(bankroll):
    deck = list(card_values.keys()) * 4
    random.shuffle(deck)

    player_hand = []
    dealer_hand = []
    current_multiplier = 1  # Default multiplier

    # Get the player's bet
    while True:
        bet = input(f"Your bankroll: {bankroll}. Enter your bet: ")
        if bet.isdigit() and 1 <= int(bet) <= bankroll:
            bet = int(bet)
            break
        else:
            print("Invalid bet. Please enter a valid number within your bankroll.")

    # Deal initial cards
    player_hand.append(deck.pop())
    dealer_hand.append(deck.pop())
    player_hand.append(deck.pop())
    dealer_hand.append(deck.pop())

    # Check if the player has a blackjack
    if calculate_hand(player_hand) == 21:
        print(f"\nYour hand: {player_hand}, Total: {calculate_hand(player_hand)}")
        print(f"Dealer's hand: {dealer_hand}, Total: {calculate_hand(dealer_hand)}")
        if calculate_hand(dealer_hand) == 21:
            print("Both you and the dealer have a blackjack! It's a tie.")
            return bankroll
        else:
            print("Blackjack! You win!")
            return bankroll + bet * 1.5

    # Print current multiplier, if it exists
    player_total = calculate_hand(player_hand)
    if player_total > 3 and player_total < 23:
        current_multiplier = multipliers.get(player_total, 1)
        print(f"Current multiplier: x{current_multiplier}")

    # Player's turn
    doubled = False
    while True:
        print(f"\nYour hand: {player_hand}, Total: {calculate_hand(player_hand)}")
        print(f"Dealer's upcard: {dealer_hand[0]}")

        if len(player_hand) == 2 and not doubled:
            choice = input("Do you want to (h)it, (s)tand, or (d)ouble down? ").lower()
        else:
            choice = input("Do you want to (h)it or (s)tand? ").lower()

        if choice == 'h':
            player_hand.append(deck.pop())
            if calculate_hand(player_hand) > 21:
                print(f"\nYour hand: {player_hand}, Total: {calculate_hand(player_hand)}")
                print("Bust! You lose.")
                return bankroll - bet
        elif choice == 's':
            break
        elif choice == 'd' and len(player_hand) == 2 and not doubled and bankroll >= bet * 2:
            bet *= 2
            doubled = True
            player_hand.append(deck.pop())
            print(f"\nYour hand after doubling down: {player_hand}, Total: {calculate_hand(player_hand)}")
            if calculate_hand(player_hand) > 21:
                print("Bust! You lose.")
                return bankroll - bet
            break
        else:
            print("Invalid choice. Please enter 'h', 's', or 'd' (if applicable and sufficient bankroll).")

    # Dealer's turn
    while calculate_hand(dealer_hand) < 17:
        dealer_hand.append(deck.pop())

    print(f"\nYour hand: {player_hand}, Total: {calculate_hand(player_hand)}")
    print(f"Dealer's hand: {dealer_hand}, Total: {calculate_hand(dealer_hand)}")

    player_total = calculate_hand(player_hand)
    dealer_total = calculate_hand(dealer_hand)

    if dealer_total > 21:
        print("Dealer busts! You win.")
        return bankroll + bet * current_multiplier
    elif player_total > dealer_total:
        print("You win!")
        return bankroll + bet * current_multiplier
    elif player_total < dealer_total:
        print("Dealer wins!")
        return bankroll - bet
    else:
        print("It's a tie!")
        return bankroll

# Start the game
bankroll = 100
while True:
    print(f"\nYour bankroll: {bankroll}")
    if bankroll <= 0:
        print("You've run out of money. Game over!")
        break

    bankroll = play_blackjack(bankroll)
    play_again = input("\nDo you want to play again? (y/n) ").lower()
    if play_again != 'y':
        break

print(f"\nYou left the game with a bankroll of {bankroll}. Thanks for playing!")
