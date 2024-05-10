# Assumptions
# 1. Dealer stands on soft 17
# 2. No insurance
# 3. No surrender
# 4. Infinite deck
# 5. Single split
# 6. No double after split

import cards
import multipliers
import hands as hands

debug_mode = True
BET = 1

RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BOLD = '\033[1m'
BLUE = '\033[34m'
C_PLAYER = '\033[46m'
C_DEALER = '\033[41m'
RESET = '\033[0m'

def debug(msg):
    if debug_mode:
        print(msg)

class GameAI():
    def _init_(self, rigged_player_hand = None, rigged_dealer_card = None):    
        self.reset(rigged_player_hand = rigged_player_hand, rigged_dealer_card = rigged_dealer_card)

    def reset(self):
        self._new_hand()
        debug(C_DEALER + "Dealer shows: " + self.dealer_hand[0] + RESET)
        self.hand_multipliers = multipliers.roll_multiplier()
        debug("Chosen multipliers: " + str(self.hand_multipliers))
        self.reward = 0
        return self._get_state()
    
    def _new_hand(self, multiplier = 1, rigged_player_hand = None, rigged_dealer_card = None):
        if (rigged_player_hand):
            player_hand = hands.Hand(rigged_player_hand)
        else:
            player_hand = hands.random_hand()
        
        if (rigged_dealer_card):
            self.dealer_upcard = rigged_dealer_card
        else:    
            self.dealer_upcard = cards.random_card()
        self.action_space = player_hand.get_choices()
        self.player_hands = [player_hand]
        self.current_multiplier = multiplier

    def _get_state(self):
       return (self.hand_multipliers, self.current_multiplier, self.dealer_upcard, [hand.get_state() for hand in self.player_hands])

    def play_step(self, action):
        if (action not in self.action_space):
            debug(RED + "Invalid action")
            exit()

        current_hand = self._get_active_hand()

        if (action == action.stand):
            current_hand.stand()
        if (action == action.hit):
            current_hand.hit()
        if (action == action.double):
            current_hand.double()
        if (action == action.split):
            self.player_hands = current_hand.split()
        
        next_hand = self._get_active_hand()
        if next_hand == None:
            next_hand_multiplier, reward, done = self._eval_game()
            self.reward += reward
            if done:
                return self._get_state(), self.reward, True, []
            else:
                self._new_hand(next_hand_multiplier)
                return self._get_state(), self.reward, False, self._get_active_hand().get_choices()
        else:
            self.action_space = next_hand.get_choices()
            debug(f"New state is {self._get_state()}")
            return self._get_state(), self.reward, False, next_hand.get_choices()

    def _get_active_hand(self):
        for hand in self.player_hands:
            if hand.is_active:
                return hand
        return None
    
    def _get_dealer_value(self):
        dealer_hand = [self.dealer_upcard]
        while cards.calculate_hand(dealer_hand) < 17:
            dealer_hand.append(cards.random_card())
        return cards.calculate_hand(dealer_hand)

    def _eval_game(self):
        dealer_value = self._get_dealer_value()
        hand_cost = self._calculate_hand_cost()
        next_hand_multiplier = 1
        won_amount = 0
        debug(C_DEALER + "Dealer hand: " + str(self.dealer_hand) + RESET)
        debug("Dealer total: " + str(dealer_value))
        done = True
        for hand in self.player_hands:
            if hand.is_blackjack():
                # at least push
                won_amount += BET
                # check if dealer has blackjack
                if not (dealer_value == 21 and len(self.dealer_hand) == 2):
                    won_amount += BET * 1.5 * self.current_multiplier
                    next_hand_multiplier = self.hand_multipliers["BJ"]
                    done = False
                continue

            hand_value = hand.get_hand_value()
            if hand_value > 21 or (dealer_value <= 21 and dealer_value > hand_value):
                # dealer wins
                continue
            if dealer_value == hand_value:
                # push
                won_amount += BET
                continue
            
            # else - WIN
            won_amount += BET * (2 if hand.is_doubled() else 1) * (self.current_multiplier + 1)
            next_hand_multiplier = max(next_hand_multiplier, self.hand_multipliers[max(hand_value, 17)])
            done = False

        return next_hand_multiplier, won_amount - hand_cost, done

    def _calculate_hand_cost(self):
        return BET + sum(BET * (2 if hand.is_doubled() else 1) for hand in self.player_hands)
