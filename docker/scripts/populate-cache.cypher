LOAD CSV WITH HEADERS FROM 'file:///provenance.csv' AS row
with row, row.left as left, row.left_type as left_type
CALL apoc.merge.node([coalesce(row.left_type, 'Default')], 
{id :toInteger(row.left),concept:coalesce(row.concept,"")}) yield node as l
with *
CALL apoc.merge.node([row.right_type], 
{id :toInteger(row.right)}) yield node as r
with *
CALL apoc.merge.relationship(l,row.relation_type, 
{user_id:coalesce(toInteger(row.user_id),1)},{},r,{}) yield rel 
RETURN r,l,rel