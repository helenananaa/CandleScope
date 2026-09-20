import pytest
from scripts.collect_okx_l2 import BookChain


def snapshot():
    return dict(seqId=12,prevSeqId=-1,bids=[['9','2','0','1']],asks=[['10','3','0','1']],checksum=0)


def test_current_zero_checksum_is_not_integrity_proof_but_sequence_chain_is_checked():
    chain=BookChain(); chain.accept('snapshot',snapshot())
    chain.accept('update',dict(seqId=15,prevSeqId=12,bids=[['9','1','0','1']],asks=[],checksum=0))
    chain.accept('update',dict(seqId=15,prevSeqId=15,bids=[],asks=[],checksum=0))
    assert chain.seq==15 and chain.book['bids']['9']=='1'
    with pytest.raises(ValueError,match='gap/reset'):
        chain.accept('update',dict(seqId=20,prevSeqId=16,bids=[],asks=[],checksum=0))


def test_reset_or_changed_repeated_sequence_invalidates_segment():
    for row in [dict(seqId=1,prevSeqId=12,bids=[],asks=[]),dict(seqId=12,prevSeqId=12,bids=[['9','3']],asks=[])]:
        chain=BookChain(); chain.accept('snapshot',snapshot())
        with pytest.raises(ValueError): chain.accept('update',row)
    with pytest.raises(ValueError,match='initial'): BookChain().accept('update',snapshot())
