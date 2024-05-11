# play.py

from hands import Action
from lbj import GameAI

# Initialize bankroll
initial_bankroll = 100
current_bankroll = initial_bankroll

# Initialize the game
game = GameAI()

action_names = {
    Action.STAND: "Stand",
    Action.HIT: "Hit",
    Action.DOUBLE: "Double",
    Action.SPLIT: "Split"
}   

# Function to print the available actions
def print_actions(actions):
    print("\nAvailable Actions:")
    for i, action in enumerate(actions):
        print(f"{i}: {action_names.get(action, 'Unknown')}")

# Function to prompt the user to select an action
def choose_action(actions):
    while True:
        try:
            choice = int(input("\nSelect an action (by number): "))
            if 0 <= choice < len(actions):
                return actions[choice]
            else:
                print("Invalid selection, please choose a valid number.")
        except ValueError:
            print("Invalid input, please enter a number.")

# Play the game until the bankroll is empty
while current_bankroll > 0:
    print(f"\nCurrent Bankroll: ${current_bankroll}")

    # Reset and get the initial state
    state = game.reset()
    actions = state[3][0]  # Available actions for the first hand

    done = False

    # Play each step until the game round is finished
    while not done:
        print_actions(actions)
        action = choose_action(actions)
        state, reward, done, actions = game.play_step(action)
        print(f"\nAction: {action}, New State: {state}, Round Reward: {reward}")

    # Adjust the bankroll
    current_bankroll += reward
    print(f"Round Complete! Current Bankroll: ${current_bankroll}")

    # Ask the user if they want to continue or quit
    continue_playing = input("\nPlay another round? (y/n): ").lower()
    if continue_playing != 'y':
        break

print(f"\nFinal Bankroll: ${current_bankroll}")
