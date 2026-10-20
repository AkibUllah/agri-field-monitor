import strawberry

from api.mutations import Mutation
from api.queries import Query

schema = strawberry.Schema(query=Query, mutation=Mutation)
