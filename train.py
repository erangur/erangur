import sys
sys.path.append('/Users/droraharon/Dev/playground/bj-monte/lbj_env')
import os
from lbj_env.lbj import GameAI
from dqn_agent import DQNAgent
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.animation import FuncAnimation
from matplotlib.ticker import MultipleLocator



latest_episode = 0  # Replace with the episode number of the latest saved model
num_episodes = 150000
save_interval = 1000
plot_interval = 200  # Update the plot every 50 episodes
window_size = 100  # Moving Average
is_rigged = False

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

env = GameAI(is_rigged)
state_size = 4
action_size = 2
agent = DQNAgent(state_size, action_size, neurons=32)
batch_size = 8

if os.path.exists(f"dqn_{agent.NEURONS}neurons_{latest_episode}.pth"):
    agent.load(f"dqn_{agent.NEURONS}neurons_{latest_episode}.pth")

scores = []  # List to store the scores of each episode
truth_scores = []  # List to store the scores based on the truth table

# Create the plot figure and axes
fig, ax = plt.subplots(figsize=(10, 5))
line4, = ax.plot([], [], label='Accuracy Moving Average')
ax.set_xlabel('Episode')
ax.set_ylabel('Score')
ax.set_title('Training Progress')
ax.legend()
ax.grid(True, linestyle='-', linewidth=0.5, color='gray', alpha=0.9)

# Set major and minor tick locators for x-axis
ax.xaxis.set_major_locator(MultipleLocator(5000))
ax.xaxis.set_minor_locator(MultipleLocator(2500))

# Set major and minor tick locators for y-axis
ax.yaxis.set_major_locator(MultipleLocator(0.1))
ax.yaxis.set_minor_locator(MultipleLocator(0.05))

# Update the plot
def update_plot():
    if len(scores) > 0:
        ax.set_xlim(0, len(scores))
        ax.set_ylim(-1, 1)
    
    
    scores_df = pd.DataFrame(scores, columns=['Score'])
    truth_scores_df = pd.DataFrame(truth_scores, columns=['Truth Score'])
    moving_avg = scores_df['Score'].rolling(window=window_size).mean()
    truth_moving_avg = truth_scores_df['Truth Score'].rolling(window=window_size).mean()
    
    # line1.set_data(range(1, len(scores)+1), scores)
    # line2.set_data(range(window_size, len(moving_avg)+window_size), moving_avg)
    # line3.set_data(range(1, len(truth_scores)+1), truth_scores)
    line4.set_data(range(window_size, len(truth_moving_avg)+window_size), truth_moving_avg)
    
    fig.canvas.draw()
    plt.pause(0.001)

hand_count = 0

# Training loop
for e in range(latest_episode, latest_episode+num_episodes):
    state = env.reset()
    state = np.reshape(state, [1, state_size])
    done = False
    truth_score = 0  # Initialize the truth score for each episode
    while not done:
        action = agent.act(state)
        next_state, reward, done = env.play_step(action, True)
        next_state = np.reshape(next_state, [1, state_size])
        
        # Compare the action taken by the model with the correct action
        correct_action = get_correct_action(state[0][:3], state[0][3])
        if action == correct_action:
            truth_score = 1
        else:
            truth_score = -1
        truth_scores.append(truth_score)  # Append the truth score to the truth_scores list
        if (e+1) % 100 in range(0,3):            
            player_hand = state[0][:6]
            dealer_upcard = state[0][3]
            print(f"Episode: {e+1}")
            print(f"Player's Hand: {player_hand}, Dealer's Upcard: {dealer_upcard}")
            print(f"Action Taken: {action}, Correct Action: {correct_action}")
            print("---")
            print (f"agent.epsilon: {agent.epsilon}")


        agent.remember(state, action, reward, next_state, done)
        state = next_state
        if done:
            print(f"Episode: {e+1}/{num_episodes+latest_episode}, Score: {env.score}, Truth Score: {truth_score}")
            scores.append(env.score)  # Append the score to the scores list            
            break
    if len(agent.memory) > batch_size:
        agent.replay(batch_size)
    if (e+1) % save_interval == 0:
        agent.save(f"dqn_{agent.NEURONS}neurons_{e+1}.pth")
    
    # Update the plot every plot_interval episodes
    if (e+1) % plot_interval == 0:
        update_plot()

# Update the plot one last time after the training is complete
update_plot()

# Keep the plot open until the user closes it
plt.show()
