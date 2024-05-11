import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import random
from collections import deque

ACTION = ["stand", "hit", "double", "split"]

class DQN(nn.Module):
    def __init__(self, state_size, action_size, NEURONS):
        super(DQN, self).__init__()
        self.fc1 = nn.Linear(state_size, NEURONS)
        self.fc2 = nn.Linear(NEURONS, NEURONS)
        self.fc3 = nn.Linear(NEURONS, NEURONS)
        self.fc4 = nn.Linear(NEURONS, action_size)

    def forward(self, state):
        x = torch.relu(self.fc1(state))
        x = torch.relu(self.fc2(x))
        x = torch.relu(self.fc3(x))  
        q_values = self.fc4(x)  # Update the output layer
        return q_values

class DQNAgent:
    def __init__(self, state_size, action_size, neurons = 64):
        self.state_size = state_size
        self.action_size = action_size
        self.NEURONS = neurons
        self.memory = deque(maxlen=500000)
        self.gamma = 0.995
        self.epsilon = 1.0
        self.epsilon_decay = 0.995
        self.epsilon_min = 0.015
        self.learning_rate = 0.001
        self.model = DQN(state_size, action_size, neurons)
        self.optimizer = optim.Adam(self.model.parameters(), lr=self.learning_rate)
        self.criterion = nn.MSELoss()
        self.avg_rewards = {}

    def remember(self, state, action, reward, next_state, done):
        self.memory.append((state, action, reward, next_state, done))
        state_tuple = tuple(state.flatten())
        state_action = state_tuple + (action,)
        if state_action not in self.avg_rewards:
            self.avg_rewards[state_action] = (reward, 1)
        else:
            avg_reward, count = self.avg_rewards[state_action]
            new_avg_reward = (avg_reward * count + reward) / (count + 1)
            self.avg_rewards[state_action] = (new_avg_reward, count + 1)
            print (f"\n\nupdating {state}: {ACTION[action]} for the {count+1} time\n\n")
            print (f"avg reward: {avg_reward}-->{new_avg_reward}")

    def act(self, state):
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        state = torch.FloatTensor(state)
        q_values = self.model(state)
        return torch.argmax(q_values).item()

    def replay(self, batch_size):
        minibatch = random.sample(self.memory, batch_size)
        for state, action, _, next_state, done in minibatch:
            state = torch.FloatTensor(state)
            next_state = torch.FloatTensor(next_state)
            state_tuple = tuple(state.numpy().flatten())
            state_action = state_tuple + (action,)
            avg_reward = self.avg_rewards[state_action][0]
            target = avg_reward
            if not done:
                target = avg_reward + self.gamma * torch.max(self.model(next_state)).item()
            target_f = self.model(state).clone().detach()
            target_f[0, action] = target
            self.optimizer.zero_grad()
            loss = self.criterion(self.model(state), target_f)
            loss.backward()
            self.optimizer.step()
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    def load(self, name):
        self.model.load_state_dict(torch.load(name))

    def save(self, name):
        torch.save(self.model.state_dict(), name)
