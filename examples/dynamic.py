class Counter:
    def __init__(self, start=0):
        self.value = start

    def next(self):
        self.value += 1
        return self.value


counter = Counter(10)
namespace = {"counter": counter}
exec("result = [counter.next() for _ in range(3)]", namespace)
print(namespace["result"])
