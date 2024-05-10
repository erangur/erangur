import cards
from enum import Enum

action = Enum('action', ['stand', 'hit', 'double', 'split'])

class Hand():
    def _init_(self, hand, is_doubled = False, is_active = True, is_split = False):
        self.hand = hand
        self.is_doubled = is_doubled
        self.is_active = is_active
        self.is_split = is_split

    def get_choices(self):
        choices = [action.stand, action.hit]
        if self._is_doublable():
            choices.append(action.double)
        if self._is_splittable():
            choices.append(action.split)
        return choices
    
    def get_state(self):
       return (self.get_hand_value(), self._is_soft(), self._is_splittable(), self.is_doubled, self.is_active)

    def get_hand_value(self):
        return cards.calculate_hand(self.hand)

    def is_blackjack(self):
        return cards.calculate_hand(self.hand) == 21 and len(self.hand) == 2 and not self.is_split
    
    def is_doubled(self):
        return self.is_doubled
    
    def get_choices(self):
        choices = ['h', 's']
        if len(self.hand) == 2:
            choices.append('d')
        if self.is_splittable():
            choices.append('p')
        return choices

    def hit(self):
        self.hand.append(cards.random_card())
        if cards.calculate_hand(self.hand) > 21:
            self.is_active = False

    def stand(self):
        self.is_active = False

    def double(self):
        self.hit()
        self.is_doubled = True
        self.is_active = False

    def split(self):
        return [Hand([self.hand[0]], is_split = True), Hand([self.hand[1]], is_split = True)]

    def _is_soft(self):
        return cards.calculate_hand(self.hand) - self.hand.count('Ace') * 10 <= 11
    
    def _is_splittable(self):
        return len(self.hand) == 2 and self.hand[0] == self.hand[1] and not self.is_split
    
    def _is_doublable(self):
        return len(self.hand) == 2 and not self.is_split


def random_hand():
    return Hand([cards.random_card(), cards.random_card()])

