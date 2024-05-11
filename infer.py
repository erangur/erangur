import torch
from dqn_agent import DQN
from basicbj import GameAI
import numpy as np
import sys

RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BOLD = '\033[1m'
BLUE = '\033[34m'
C_PLAYER = '\033[46m'
C_DEALER = '\033[41m'
RESET = '\033[0m'

# Check if model path is provided as argument, otherwise use default
if len(sys.argv) > 1:
    model_path = sys.argv[1]
else:
    model_path = f"dqn_{neurons}neurons_13000.pth"

exit_on_error = False
is_rigged=False
neurons = 32
num_episodes = 2000
# is_rigged=True
# exit_on_error = True

ACTIONS = ['STAND','HIT']

def get_correct_action(player_hand, dealer_upcard):
    player_total = player_hand[0]
    is_soft = player_hand[1]
    is_pair = player_hand[2]
    
    if is_soft:
        if player_total >= 19:
            return 0  # Stand
        elif player_total == 18 and dealer_upcard in [2, 3, 4, 5, 6, 7, 8]:
            return 0  # Stand
        else:
            return 1  # Hit
    else:
        if player_total >= 17:
            return 0  # Stand
        elif player_total >= 13 and dealer_upcard <= 6:
            return 0  # Stand
        elif player_total == 12 and dealer_upcard >= 4 and dealer_upcard <= 6:
            return 0 # Stand
        else:
            return 1  # Hit


# Create an instance of the DQN model
state_size = 4
action_size = 2
model = DQN(state_size, action_size, NEURONS=neurons)

# Load the trained model parameters
model.load_state_dict(torch.load(model_path))
model.eval()  # Set the model to evaluation mode

# Create an instance of the GameAI environment
env = GameAI(is_rigged)

score=0
loses, wins = 0, 0
correct_acts, incorrect_acts = 0, 0
errors = np.zeros((22,2,12))
for episode in range(num_episodes):
    state = env.reset()
    print (state)
    state = torch.FloatTensor([state]).unsqueeze(0)  # Convert state to a FloatTensor with shape (1, 1)
    done = False
    print(f"Episode {episode+1}:")
    
    while not done:
        with torch.no_grad():
            q_values = model(state)
            action = torch.argmax(q_values).item()
            correct_action = get_correct_action(state[0][0][0:3], state[0][0][3])            
            if action == correct_action:
                print (C_DEALER + f"model predicted {ACTIONS[action]}, truth is {ACTIONS[correct_action]}\n tensor: {q_values}" + RESET)
                correct_acts += 1
            else:
                incorrect_acts += 1          
                print (C_PLAYER + f"model predicted {ACTIONS[action]}, truth is {ACTIONS[correct_action]}\n tensor: {q_values}" + RESET)
                # print (f"model predicted {ACTIONS[action]}, truth is {ACTIONS[correct_action]}\n tensor: {q_values}")
                if exit_on_error:
                    if int(state[0][0][1]):
                        soft = " soft"
                    else: 
                        soft = ""                                    
                    exit()                
                total=int(state[0][0][0])
                soft = int(state[0][0][1])
                dealer = int(state[0][0][3])                
                errors[total][soft][dealer] += 1                

        next_state, reward, done = env.play_step(action, p=True)
        state = torch.FloatTensor([next_state]).unsqueeze(0)  # Convert next_state to a FloatTensor with shape (1, 1)        
    
    print(f"Episode score: {env.score}\n")
    score += env.score
    if env.score > 0:
        wins += 1
    elif env.score < 0:
        loses += 1
avg_score = score/num_episodes
non_zero_indices = np.nonzero(errors)
indices_sorted_by_frequency = np.argsort(errors[non_zero_indices])[::-1]
for idx in indices_sorted_by_frequency:
    total, soft, dealer = non_zero_indices[0][idx], non_zero_indices[1][idx], non_zero_indices[2][idx]
    error_value = errors[total, soft, dealer]
    print(f"Errors at total={total}, soft={soft}, dealer={dealer}: {error_value}")

print (f"avg score: {avg_score}")
print (f"win rate: {wins/(wins+loses)}")
print (f"correct acts rates: {correct_acts/(incorrect_acts+correct_acts)}")