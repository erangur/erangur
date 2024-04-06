import random

RED = '\033[91m'
GREEN = '\033[92m'
RESET = '\033[0m'

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
def setup_hand(hand, new_hand, deck):
    hand.clear()
    hand.extend(new_hand)
    deck.remove(new_hand[0])
    deck.remove(new_hand[1])
    return hand, deck

# Function to play a game of blackjack
def play_blackjack(bankroll, multiplier):
    deck = list(card_values.keys()) * 4
    random.shuffle(deck)

    player_hand = []
    dealer_hand = []
    current_multiplier = multiplier
    # Player's bet is fixed on 10
    bet = 10
    bankroll -= bet

    # Deal initial cards
    player_hand.append(deck.pop())
    dealer_hand.append(deck.pop())
    player_hand.append(deck.pop())
    dealer_hand.append(deck.pop())

    # Debug
    # player_hand, deck = setup_hand(player_hand, ['4', '4'], deck)
    # dealer_hand, deck = setup_hand(dealer_hand, ['10', '3'], deck)
    
    # Check if the player has a blackjack
    if calculate_hand(player_hand) == 21:
        print(f"\nYour hand: {player_hand}, Total: {calculate_hand(player_hand)}")
        print(f"Dealer's hand: {dealer_hand}, Total: {calculate_hand(dealer_hand)}")
        if calculate_hand(dealer_hand) == 21:
            print("Both you and the dealer have a blackjack! It's a tie.")
            return bankroll, 1
        else:
            print("Blackjack! You win!")
            new_bankroll = bankroll + bet * 1.5 * current_multiplier
            return new_bankroll, multipliers.get(22, 1)

    print(f"Current multiplier: x{current_multiplier}")

    # Player's turn
    doubled = False
    while True:
        print(f"\nYour hand: {player_hand}, Total: {calculate_hand(player_hand)}")
        print(f"Dealer's upcard: {dealer_hand[0]}")

        if len(player_hand) == 2 and not doubled and player_hand[0]==player_hand[1]:
            choice = input("Do you want to (h)it, (s)tand, s(p)lit or (d)ouble down? ").lower()
        elif len(player_hand) == 2 and not doubled:
            choice = input("Do you want to (h)it, (s)tand, or (d)ouble down? ").lower()
        else:
            choice = input("Do you want to (h)it or (s)tand? ").lower()

        if choice == 'h':
            player_hand.append(deck.pop())
            if calculate_hand(player_hand) > 21:
                print(f"\nYour hand: {player_hand}, Total: {calculate_hand(player_hand)}")
                print(RED + "Bust! You lose." + RESET)
                return bankroll - bet, 1
        elif choice == 's':
            break
        elif choice == 'd' and len(player_hand) == 2 and not doubled and bankroll >= bet * 2:
            bet *= 2
            doubled = True
            player_hand.append(deck.pop())
            print(f"\nYour hand after doubling down: {player_hand}, Total: {calculate_hand(player_hand)}")
            if calculate_hand(player_hand) > 21:
                print(RED + "Bust! You lose." + RESET)
                return bankroll - bet
            break
        elif choice == 'p' and len(player_hand) == 2 and not doubled and bankroll >= bet * 2:
            #todo: handle splits
            print (RED + "Splitting not supported yet!" + RESET)
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
        print(GREEN + "Dealer busts! You win." + RESET)
        new_bankroll = bankroll + bet * current_multiplier
        print (f"Setting new multiplier for {player_total}: x{multipliers.get(player_total, 1)}")
        new_multiplier = multipliers.get(player_total, 1) 
        return new_bankroll, new_multiplier
    elif player_total > dealer_total:
        print(GREEN + "You win!" + RESET)
        new_bankroll = bankroll + bet * current_multiplier
        print (f"Setting new multiplier for {player_total}: x{multipliers.get(player_total, 1)}")
        new_multiplier = multipliers.get(player_total, 1) 
        return new_bankroll, new_multiplier
    elif player_total < dealer_total:
        print(RED + "Dealer wins!" + RESET)
        current_multiplier = 1
        return bankroll - bet, 1
    else:
        print(RED + "Push!" + RESET)
        current_multiplier = 1
        return bankroll, 1

# Start the game
bankroll = 200
multiplier = 1
handcount = 0
while True:
    print(f"\nYour bankroll: {bankroll}")
    # player_total, dealer_total = setup_hand(player_hand, dealer_hand, player_total, dealer_total)

    if bankroll <= 0:
        print("You've run out of money. Game over!")
        break
    bankroll, multiplier = play_blackjack(bankroll, multiplier)
    print(f"Hand: {handcount}, Bankroll: {bankroll}, Multiplier: {multiplier}")
    handcount += 1
    # if handcount > 2: 
    #     break
    # play_again = input("\nDo you want to play again? (y/n) ").lower()
    # if play_again != 'y':
    #     break

print(f"\nYou left the game with a bankroll of {bankroll}. Thanks for playing!")
